"""Applying a check to the database: status, history, rotation and notifications."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lifeline.models import CaptureMethod, Check, CheckOutcome, Site, SiteStatus
from lifeline.services.crypto import Cipher
from lifeline.services.runner import CheckRunner
from lifeline.services.store import load_settings_row
from tests.conftest import RecordingSender, make_fetch_result

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
ROTATED_STATE = {
    "cookies": [
        {
            "name": "session",
            "value": "rotated",
            "domain": ".example.org",
            "path": "/",
            "expires": 4102444800.0,
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        },
        # A login page leaves its analytics cookies behind; this one expires in 2027 and says
        # nothing about the session, so it must not be what the stored expiry reports.
        {
            "name": "_dd_s",
            "value": "sampled",
            "domain": ".example.org",
            "path": "/",
            "expires": 1800000000.0,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        },
    ],
    "origins": [],
}


@pytest.fixture(autouse=True)
async def configured_destination(db: AsyncSession) -> None:
    """Give every runner test somewhere to notify, so suppression is what is being tested."""
    row = await load_settings_row(db)
    row.apprise_urls = "tgram://token/chat"
    await db.commit()


async def reload(db: AsyncSession, site: Site) -> Site:
    """Re-read a site from the database, discarding anything this session has cached.

    The runner commits through its own sessions, so the test's objects are stale. Detaching
    first rather than expiring matters: an expired relationship would be lazily loaded on
    attribute access, which async SQLAlchemy cannot do and reports as MissingGreenlet.
    """
    db.expunge_all()
    result = await db.execute(
        select(Site).options(selectinload(Site.session)).where(Site.id == site.id)
    )
    return result.scalar_one()


class TestSuccessfulCheck:
    async def test_marks_the_site_alive_and_schedules_the_next_check(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner().run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.status is SiteStatus.ALIVE
        assert site.last_ok_at == NOW
        assert site.last_check_at == NOW
        assert site.next_check_at == NOW + timedelta(days=7)

    async def test_records_the_check(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner().run(logged_in_site.id, now=NOW)

        check = (await db.execute(select(Check))).scalar_one()
        assert check.outcome is CheckOutcome.OK
        assert check.status_code == 200
        assert check.final_url == "https://example.org/home"

    async def test_clears_a_previous_failure_count(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        logged_in_site.consecutive_failures = 4
        logged_in_site.status = SiteStatus.ERROR
        await db.commit()

        await make_runner().run(logged_in_site.id, now=NOW)

        assert (await reload(db, logged_in_site)).consecutive_failures == 0

    async def test_says_nothing_when_a_healthy_site_stays_healthy(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.status = SiteStatus.ALIVE
        await db.commit()

        await make_runner().run(logged_in_site.id, now=NOW)

        assert sender.sent == []


class TestRotation:
    async def test_a_rotated_session_is_written_back(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        cipher: Cipher,
        make_runner: Callable[..., CheckRunner],
    ) -> None:
        # The behaviour the tool depends on: keeping the old cookie would discard the
        # extension this ping just earned, or invalidate the session outright.
        runner = make_runner(make_fetch_result(state=ROTATED_STATE, rotated=True))

        await runner.run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert cipher.decrypt_json(site.session.state) == ROTATED_STATE
        assert site.session.rotated_at == NOW
        assert site.session.cookie_names == "_dd_s,session"

    async def test_an_unrotated_session_is_left_alone(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        original = logged_in_site.session.state

        await make_runner(make_fetch_result(rotated=False)).run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.session.state == original
        assert site.session.rotated_at is None

    async def test_records_when_the_last_cookie_expires(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # The last, not the first: a login page leaves analytics cookies behind that expire in
        # minutes and say nothing about the session.
        runner = make_runner(make_fetch_result(state=ROTATED_STATE, rotated=True))

        await runner.run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.session.expires_at == datetime(2100, 1, 1, tzinfo=UTC)


class TestLapsedSession:
    async def test_a_site_with_no_session_is_lapsed(
        self, db: AsyncSession, site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner().run(site.id, now=NOW)

        assert (await reload(db, site)).status is SiteStatus.LAPSED

    async def test_notifies_the_first_time_a_session_lapses(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.status = SiteStatus.ALIVE
        logged_in_site.login_url_pattern = "login.php"
        await db.commit()
        runner = make_runner(make_fetch_result(final_url="https://example.org/login.php"))

        await runner.run(logged_in_site.id, now=NOW)

        assert len(sender.sent) == 1
        assert "needs a new login" in sender.titles[0]

    async def test_does_not_repeat_itself_on_the_next_check(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.status = SiteStatus.LAPSED
        logged_in_site.failure_pattern = "please log in"
        await db.commit()

        await make_runner(make_fetch_result(status_code=200, body="please log in")).run(
            logged_in_site.id, now=NOW
        )

        assert sender.sent == []

    async def test_notifies_when_a_session_starts_working_again(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.status = SiteStatus.LAPSED
        await db.commit()

        await make_runner().run(logged_in_site.id, now=NOW)

        assert "is alive again" in sender.titles[0]

    async def test_unreadable_state_reads_as_needing_a_new_login(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # A changed encryption key leaves the stored session unusable, and the remedy is
        # the same as any dead session: log in again.
        logged_in_site.session.state = b"not-a-fernet-token"
        await db.commit()

        await make_runner().run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.status is SiteStatus.LAPSED
        check = (await db.execute(select(Check))).scalar_one()
        assert "could not be decrypted" in check.detail


class TestErrors:
    async def test_a_failing_request_is_an_error_not_a_lapse(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner(make_fetch_result(status_code=503)).run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.status is SiteStatus.ERROR
        assert site.consecutive_failures == 1

    async def test_stays_quiet_below_the_error_threshold(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        # A single blip is not worth waking someone for.
        await make_runner(make_fetch_result(status_code=503)).run(logged_in_site.id, now=NOW)

        assert sender.sent == []

    async def test_notifies_once_the_failures_persist(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.consecutive_failures = 2
        await db.commit()

        await make_runner(httpx.ConnectError("no route")).run(logged_in_site.id, now=NOW)

        assert "cannot be reached" in sender.titles[0]

    async def test_backs_off_rather_than_waiting_the_full_interval(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner(httpx.ReadTimeout("slow")).run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.next_check_at < NOW + timedelta(days=1)

    async def test_a_network_failure_does_not_touch_the_stored_session(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        original = logged_in_site.session.state

        await make_runner(httpx.ConnectError("down")).run(logged_in_site.id, now=NOW)

        assert (await reload(db, logged_in_site)).session.state == original


class TestAtRisk:
    async def test_a_healthy_site_running_out_of_time_is_flagged(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        logged_in_site.inactivity_limit_days = 3
        await db.commit()

        await make_runner().run(logged_in_site.id, now=NOW)

        site = await reload(db, logged_in_site)
        assert site.status is SiteStatus.AT_RISK
        assert "running out of time" in sender.titles[0]

    async def test_a_lapsed_site_is_not_also_reported_as_at_risk(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        # It has already been reported as needing a login; a second message adds nothing.
        # A site with a session, because one that never had a session says nothing at all.
        logged_in_site.inactivity_limit_days = 1
        logged_in_site.last_ok_at = NOW - timedelta(days=1)
        logged_in_site.login_url_pattern = "login.php"
        await db.commit()
        runner = make_runner(
            make_fetch_result(final_url="https://example.org/login.php", state=None)
        )

        await runner.run(logged_in_site.id, now=NOW)

        assert len(sender.sent) == 1
        assert "needs a new login" in sender.titles[0]


class TestRunDue:
    async def test_checks_every_due_site(
        self, db: AsyncSession, make_runner: Callable[..., CheckRunner], cipher: Cipher
    ) -> None:
        from lifeline.models import SiteSession
        from tests.conftest import SAMPLE_STATE, make_site

        for name in ("one", "two"):
            row = make_site(id=None, name=name)
            row.session = SiteSession(
                state=cipher.encrypt_json(SAMPLE_STATE),
                captured_via=CaptureMethod.IMPORT,
                captured_at=NOW,
            )
            db.add(row)
        await db.commit()

        checked = await make_runner().run_due(now=NOW)

        assert len(checked) == 2
        assert len((await db.execute(select(Check))).scalars().all()) == 2

    async def test_reports_a_missing_site_rather_than_raising(
        self, make_runner: Callable[..., CheckRunner]
    ) -> None:
        assert await make_runner().run(9999, now=NOW) is None

    async def test_one_sites_failure_does_not_stop_the_sweep(
        self,
        db: AsyncSession,
        make_runner: Callable[..., CheckRunner],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.conftest import make_site

        db.add_all([make_site(id=None, name="one"), make_site(id=None, name="two")])
        await db.commit()
        runner = make_runner()
        calls: list[int] = []
        original = runner.run

        async def exploding(site_id: int, **kwargs: object) -> None:
            calls.append(site_id)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return await original(site_id, **kwargs)

        monkeypatch.setattr(runner, "run", exploding)

        checked = await runner.run_due(now=NOW)

        assert len(checked) == 2
        assert len(calls) == 2


class TestStoreSession:
    async def test_saves_an_encrypted_session_and_resets_the_site(
        self,
        db: AsyncSession,
        site: Site,
        cipher: Cipher,
        make_runner: Callable[..., CheckRunner],
    ) -> None:
        site.status = SiteStatus.LAPSED
        site.consecutive_failures = 5
        site.next_check_at = NOW + timedelta(days=7)
        await db.commit()

        await make_runner().store_session(
            site.id, ROTATED_STATE, CaptureMethod.BROWSER, user_agent="Agent/2", now=NOW
        )

        stored = await reload(db, site)
        assert cipher.decrypt_json(stored.session.state) == ROTATED_STATE
        assert stored.session.captured_via is CaptureMethod.BROWSER
        assert stored.user_agent == "Agent/2"
        # A fresh session is an unknown quantity, due for a check straight away.
        assert stored.status is SiteStatus.UNKNOWN
        assert stored.consecutive_failures == 0
        assert stored.next_check_at is None

    async def test_replaces_an_existing_session(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        from lifeline.models import SiteSession

        await make_runner().store_session(
            logged_in_site.id, ROTATED_STATE, CaptureMethod.IMPORT, now=NOW
        )

        db.expunge_all()
        rows = (await db.execute(select(SiteSession))).scalars().all()
        assert len(rows) == 1
        assert rows[0].captured_via is CaptureMethod.IMPORT

    async def test_keeps_the_existing_user_agent_when_none_is_given(
        self, db: AsyncSession, site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        site.user_agent = "Agent/1"
        await db.commit()

        await make_runner().store_session(site.id, ROTATED_STATE, CaptureMethod.IMPORT, now=NOW)

        assert (await reload(db, site)).user_agent == "Agent/1"

    async def test_clears_the_notification_cooldown(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        # Without this, the message saying the new login also failed would be suppressed.
        runner = make_runner(make_fetch_result(status_code=200, body="please log in"))
        logged_in_site.status = SiteStatus.ALIVE
        logged_in_site.failure_pattern = "please log in"
        await db.commit()
        await runner.run(logged_in_site.id, now=NOW)
        assert len(sender.sent) == 1

        await make_runner().store_session(
            logged_in_site.id, ROTATED_STATE, CaptureMethod.BROWSER, now=NOW
        )
        await runner.run(logged_in_site.id, now=NOW)

        assert len(sender.sent) == 2

    async def test_rejects_a_session_for_a_site_that_does_not_exist(
        self, make_runner: Callable[..., CheckRunner]
    ) -> None:
        with pytest.raises(LookupError):
            await make_runner().store_session(4242, ROTATED_STATE, CaptureMethod.IMPORT, now=NOW)


class TestUnavailableMethod:
    async def test_a_browser_check_without_a_browser_fetcher_is_reported(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        sessionmaker,
        settings,
        cipher: Cipher,
        notifier,
    ) -> None:
        # A deployment built without the browser: the site's configuration cannot be honoured,
        # and saying so is better than recording a check that never happened.
        from lifeline.models import PingMethod
        from lifeline.services.checker import HttpFetcher

        logged_in_site.ping_method = PingMethod.BROWSER
        await db.commit()
        runner = CheckRunner(
            sessionmaker, settings, cipher, notifier, {PingMethod.HTTP: HttpFetcher(settings)}
        )

        with pytest.raises(RuntimeError, match="not available"):
            await runner.run(logged_in_site.id, now=NOW)


class TestLogging:
    async def test_info_records_every_check(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # The line a person looks for. Before this existed, a successful check wrote nothing from
        # the application at all — only an incidental line from the HTTP client.
        with caplog.at_level(logging.INFO, logger="lifeline.services.runner"):
            await make_runner().run(logged_in_site.id, now=NOW)

        assert any("checked example: ok" in message for message in caplog.messages)

    async def test_info_records_a_change_of_state(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        logged_in_site.status = SiteStatus.LAPSED
        await db.commit()

        with caplog.at_level(logging.INFO, logger="lifeline.services.runner"):
            await make_runner().run(logged_in_site.id, now=NOW)

        assert any("lapsed -> alive" in message for message in caplog.messages)

    async def test_info_says_nothing_when_the_state_is_unchanged(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        logged_in_site.status = SiteStatus.ALIVE
        await db.commit()

        with caplog.at_level(logging.INFO, logger="lifeline.services.runner"):
            await make_runner().run(logged_in_site.id, now=NOW)

        assert not any("->" in message for message in caplog.messages)

    async def test_debug_adds_the_reasoning(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        logged_in_site.login_url_pattern = "login.php"
        await db.commit()
        runner = make_runner(make_fetch_result(final_url="https://example.org/login.php"))

        with caplog.at_level(logging.DEBUG, logger="lifeline.services.runner"):
            await runner.run(logged_in_site.id, now=NOW)

        joined = "\n".join(caplog.messages)
        assert "ended at https://example.org/login.php" in joined
        assert "is the site's login page" in joined

    async def test_debug_never_records_a_cookie_value(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Cookie names are useful in a log; the values are the session itself. The value here is
        # deliberately not a word the log uses for anything else.
        secret = "UNMISTAKABLE-COOKIE-VALUE"
        state = {
            "cookies": [{**ROTATED_STATE["cookies"][0], "value": secret}],
            "origins": [],
        }
        runner = make_runner(make_fetch_result(state=state, rotated=True))

        with caplog.at_level(logging.DEBUG, logger="lifeline.services.runner"):
            await runner.run(logged_in_site.id, now=NOW)

        joined = "\n".join(caplog.messages)
        assert "cookies session" in joined
        assert secret not in joined

    async def test_info_records_a_captured_session(
        self,
        db: AsyncSession,
        site: Site,
        make_runner: Callable[..., CheckRunner],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.INFO, logger="lifeline.services.runner"):
            await make_runner().store_session(
                site.id, ROTATED_STATE, CaptureMethod.BROWSER, now=NOW
            )

        assert any("stored a session for example" in message for message in caplog.messages)


class TestScopedToTheSite:
    """Cookies from elsewhere are dropped on every write, not only on capture."""

    def state_with_a_stranger(self) -> dict:
        return {
            "cookies": [
                {"name": "session", "value": "s", "domain": ".example.org", "path": "/"},
                {"name": "_gh_sess", "value": "g", "domain": "github.com", "path": "/"},
            ],
            "origins": [],
        }

    async def test_a_capture_keeps_only_the_sites_own_cookies(
        self, db: AsyncSession, site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        await make_runner().store_session(
            site.id, self.state_with_a_stranger(), CaptureMethod.BROWSER, now=NOW
        )

        stored = (await reload(db, site)).session
        assert stored.cookie_names == "session"

    async def test_a_write_back_cleans_a_session_that_already_held_them(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # A session captured before the scoping rule existed heals on its next check rather than
        # needing a fresh login.
        runner = make_runner(make_fetch_result(state=self.state_with_a_stranger(), rotated=True))

        await runner.run(logged_in_site.id, now=NOW)

        stored = (await reload(db, logged_in_site)).session
        assert stored.cookie_names == "session"

    async def test_a_fresh_capture_has_not_rotated(
        self, db: AsyncSession, site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # Nothing has reissued it yet, so the interface must not claim otherwise.
        await make_runner().store_session(
            site.id, self.state_with_a_stranger(), CaptureMethod.BROWSER, now=NOW
        )

        assert (await reload(db, site)).session.rotated_at is None


class TestExpiryWithoutRotation:
    """A site that never reissues its cookies still has an expiry that has to be right."""

    async def test_a_successful_check_fills_in_a_missing_expiry(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # Nothing rotates, so nothing is re-encrypted — but the column is what decides whether
        # the site is warned about, and it must not stay empty for the life of the session.
        logged_in_site.session.expires_at = None
        await db.commit()

        await make_runner(make_fetch_result(rotated=False)).run(logged_in_site.id, now=NOW)

        stored = (await reload(db, logged_in_site)).session
        assert stored.expires_at == datetime(2100, 1, 1, tzinfo=UTC)

    async def test_leaves_the_session_itself_untouched(
        self, db: AsyncSession, logged_in_site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # Reading it to compute an expiry is not a reason to rewrite it, which would claim a
        # rotation that never happened.
        original = logged_in_site.session.state

        await make_runner(make_fetch_result(rotated=False)).run(logged_in_site.id, now=NOW)

        stored = (await reload(db, logged_in_site)).session
        assert stored.state == original
        assert stored.rotated_at is None


class TestASessionThatNeverExisted:
    """Adding a site must not immediately report a login as lost."""

    async def test_says_nothing_about_a_site_that_has_never_been_logged_into(
        self, site: Site, make_runner: Callable[..., CheckRunner], sender: RecordingSender
    ) -> None:
        # A new site is due at once, so the scheduler checks it within the minute — while
        # someone is still part-way through logging in.
        await make_runner().run(site.id, now=NOW)

        assert sender.sent == []

    async def test_still_records_the_check(
        self, db: AsyncSession, site: Site, make_runner: Callable[..., CheckRunner]
    ) -> None:
        # Silent, not invisible: the history should still say the site has nothing to ping with.
        check = await make_runner().run(site.id, now=NOW)

        assert check.outcome is CheckOutcome.LOGIN_EXPIRED
        assert (await reload(db, site)).status is SiteStatus.LAPSED

    async def test_reports_a_captured_session_that_does_not_work(
        self,
        db: AsyncSession,
        logged_in_site: Site,
        make_runner: Callable[..., CheckRunner],
        sender: RecordingSender,
    ) -> None:
        # The opposite case, which must keep working: a login was just captured and the first
        # check with it fails. That is worth hearing about immediately.
        logged_in_site.login_url_pattern = "login.php"
        await db.commit()
        runner = make_runner(
            make_fetch_result(final_url="https://example.org/login.php", state=None)
        )

        await runner.run(logged_in_site.id, now=NOW)

        assert len(sender.sent) == 1
