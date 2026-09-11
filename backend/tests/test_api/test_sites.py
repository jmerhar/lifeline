"""Managing sites over HTTP."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lifeline.models import CaptureMethod, PingMethod, Site, SiteSession, SiteStatus, User

NEW_SITE = {
    "name": "example",
    "ping_url": "https://example.org/home",
    "login_url": "https://example.org/login.php",
    "interval_days": 14,
    "inactivity_limit_days": 90,
    "login_url_pattern": "login.php",
    "success_pattern": "Logged in as",
}


@pytest.fixture
async def created(logged_in: httpx.AsyncClient) -> dict:
    """One site, created through the API."""
    response = await logged_in.post("/api/sites", json=NEW_SITE)
    assert response.status_code == 201
    return response.json()


class TestCreate:
    async def test_stores_what_was_sent(self, created: dict) -> None:
        assert created["name"] == "example"
        assert created["interval_days"] == 14
        assert created["inactivity_limit_days"] == 90
        assert created["status"] == SiteStatus.UNKNOWN
        assert created["session"] is None

    async def test_a_new_site_has_an_empty_pulse(self, created: dict) -> None:
        assert created["pulse"] == []

    async def test_rejects_a_duplicate_name(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        assert (await logged_in.post("/api/sites", json=NEW_SITE)).status_code == 409

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "data:text/html,x", "ftp://host/x"])
    async def test_rejects_a_url_that_is_not_http(
        self, logged_in: httpx.AsyncClient, url: str
    ) -> None:
        # The ping is made with the site's cookies; a file:// target would be a way to make
        # the server read something it should not.
        response = await logged_in.post("/api/sites", json={**NEW_SITE, "ping_url": url})

        assert response.status_code == 422

    async def test_rejects_an_interval_of_zero(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.post("/api/sites", json={**NEW_SITE, "interval_days": 0})

        assert response.status_code == 422

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/sites", json=NEW_SITE)).status_code == 401


class TestRead:
    async def test_lists_sites(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.get("/api/sites")

        assert [site["name"] for site in response.json()] == ["example"]

    async def test_shows_one_site(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        assert (await logged_in.get(f"/api/sites/{created['id']}")).json()["name"] == "example"

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/sites/404")).status_code == 404

    async def test_never_returns_the_stored_session_itself(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict
    ) -> None:
        # The session is equivalent to being logged in; it must not leave the server.
        site = await db.get(Site, created["id"])
        site.session = SiteSession(
            state=cipher.encrypt_json({"cookies": [], "origins": []}),
            captured_via=CaptureMethod.IMPORT,
            captured_at=site.created_at,
            cookie_names="session,uid",
        )
        await db.commit()

        body = (await logged_in.get(f"/api/sites/{created['id']}")).json()

        assert body["session"]["cookie_names"] == ["session", "uid"]
        assert "state" not in body["session"]


class TestUpdate:
    async def test_changes_a_field(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "interval_days": 30}
        )

        assert response.json()["interval_days"] == 30

    async def test_can_rename_a_site(self, logged_in: httpx.AsyncClient, created: dict) -> None:
        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "name": "renamed"}
        )

        assert response.json()["name"] == "renamed"

    async def test_rejects_renaming_onto_another_site(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post("/api/sites", json={**NEW_SITE, "name": "other"})

        response = await logged_in.put(
            f"/api/sites/{created['id']}", json={**NEW_SITE, "name": "other"}
        )

        assert response.status_code == 409

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.put("/api/sites/404", json=NEW_SITE)).status_code == 404


class TestDelete:
    async def test_removes_the_site(
        self, logged_in: httpx.AsyncClient, created: dict, db: AsyncSession
    ) -> None:
        response = await logged_in.delete(f"/api/sites/{created['id']}")

        assert response.status_code == 204
        db.expunge_all()
        assert (await db.execute(select(Site))).scalars().all() == []

    async def test_leaves_the_login_browsers_profile_alone(
        self, logged_in: httpx.AsyncClient, created: dict, services
    ) -> None:
        # One profile is shared by every site, so deleting it would take the password manager's
        # setup with it. The next first login for any site empties the cookie jar instead.
        profile = services.browser.profile_dir
        profile.mkdir(parents=True, exist_ok=True)
        (profile / "Extension State").write_text("the password manager's setup")

        await logged_in.delete(f"/api/sites/{created['id']}")

        assert (profile / "Extension State").exists()

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.delete("/api/sites/404")).status_code == 404


class TestCheckNow:
    async def test_runs_a_check_and_returns_it(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(f"/api/sites/{created['id']}/check")

        assert response.status_code == 200
        # No session has been captured, so the honest answer is that a login is needed.
        assert response.json()["outcome"] == "login_expired"

    async def test_appears_in_the_history(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(f"/api/sites/{created['id']}/check")

        history = (await logged_in.get(f"/api/sites/{created['id']}/checks")).json()

        assert len(history) == 1

    async def test_shows_up_in_the_pulse(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(f"/api/sites/{created['id']}/check")

        listed = (await logged_in.get("/api/sites")).json()[0]

        assert listed["pulse"] == ["login_expired"]

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.post("/api/sites/404/check")).status_code == 404


class TestSessionImport:
    async def test_stores_a_pasted_cookie_header(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(
            f"/api/sites/{created['id']}/session/import",
            json={"text": "uid=1234; pass=abcdef", "user_agent": "Pasted/1.0"},
        )

        assert response.status_code == 200
        site = (await logged_in.get(f"/api/sites/{created['id']}")).json()
        assert site["session"]["cookie_names"] == ["pass", "uid"]
        assert site["session"]["captured_via"] == "import"
        assert site["user_agent"] == "Pasted/1.0"

    async def test_rejects_text_that_is_not_cookies(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "just some prose"}
        )

        assert response.status_code == 422
        assert "name=value" in response.json()["detail"]

    async def test_a_check_after_importing_uses_the_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "uid=1234"}
        )

        outcome = (await logged_in.post(f"/api/sites/{created['id']}/check")).json()

        assert outcome["outcome"] == "ok"

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        response = await logged_in.post("/api/sites/404/session/import", json={"text": "a=b"})

        assert response.status_code == 404


class TestSessionRemoval:
    async def test_discards_the_stored_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        await logged_in.post(
            f"/api/sites/{created['id']}/session/import", json={"text": "uid=1234"}
        )

        response = await logged_in.delete(f"/api/sites/{created['id']}/session")

        assert response.status_code == 200
        assert (await logged_in.get(f"/api/sites/{created['id']}")).json()["session"] is None

    async def test_is_harmless_when_there_is_no_session(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        assert (await logged_in.delete(f"/api/sites/{created['id']}/session")).status_code == 200


class TestHistory:
    async def test_caps_an_outrageous_limit(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.get(f"/api/sites/{created['id']}/checks?limit=100000")

        assert response.status_code == 200

    async def test_reports_a_missing_site(self, logged_in: httpx.AsyncClient) -> None:
        assert (await logged_in.get("/api/sites/404/checks")).status_code == 404


class TestRiskReason:
    """A status word alone leaves someone reading "due soon" with nothing to act on."""

    async def run_out_of_time(self, db: AsyncSession, site_id: int) -> None:
        """Put a site two days from its inactivity deadline, with no check due before then."""
        site = await db.get(Site, site_id)
        assert site is not None
        # Alive, because a reason is only the open question for a site whose session still works.
        site.status = SiteStatus.ALIVE
        site.last_ok_at = datetime.now(UTC) - timedelta(days=88)
        site.next_check_at = datetime.now(UTC) + timedelta(days=30)
        await db.commit()

    async def test_says_why_a_site_needs_attention(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        await self.run_out_of_time(db, created["id"])

        body = (await logged_in.get("/api/sites")).json()

        assert "the account lapses in" in body[0]["risk"]

    async def test_stays_quiet_about_a_healthy_site(self, created: dict) -> None:
        assert created["risk"] is None

    async def test_says_nothing_for_a_site_already_reported_lapsed(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        # "The account lapses in 2 days" under a lapsed badge describes a race already lost.
        await self.run_out_of_time(db, created["id"])
        site = await db.get(Site, created["id"])
        site.status = SiteStatus.LAPSED
        await db.commit()

        body = (await logged_in.get("/api/sites")).json()

        assert body[0]["risk"] is None

    async def test_answers_for_one_site_too(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        await self.run_out_of_time(db, created["id"])

        body = (await logged_in.get(f"/api/sites/{created['id']}")).json()

        assert "the account lapses in" in body["risk"]


class TestDetectingTheRules:
    """Working out a site's detection rules from a signed-in and a signed-out fetch."""

    async def give_it_a_session(self, db: AsyncSession, cipher, site_id: int) -> None:
        """A stored session, so there is a signed-in side to compare against."""
        site = await db.get(Site, site_id)
        site.session = SiteSession(
            state=cipher.encrypt_json(
                {
                    "cookies": [
                        {"name": "session", "value": "v", "domain": "example.org", "path": "/"}
                    ],
                    "origins": [],
                }
            ),
            captured_via=CaptureMethod.IMPORT,
            captured_at=site.created_at,
            cookie_names="session",
        )
        await db.commit()

    async def test_reports_what_the_two_fetches_disagree_about(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        await self.give_it_a_session(db, cipher, created["id"])

        def answer(request: httpx.Request) -> httpx.Response:
            if request.headers.get("cookie"):
                return httpx.Response(200, text="<a>Log out</a>")
            return httpx.Response(
                200, text="<p>Remember me</p>", request=request
            )

        stub.get("https://example.org/home").mock(side_effect=answer)

        body = (await logged_in.post(f"/api/sites/{created['id']}/detect")).json()

        assert body["success_pattern"] == "Log out"
        assert body["failure_pattern"] == "Remember me"
        assert body["notes"]

    async def test_refuses_without_a_session_to_compare_against(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        # Half the comparison is what the page looks like to somebody logged in.
        response = await logged_in.post(f"/api/sites/{created['id']}/detect")

        assert response.status_code == 409
        assert "log in to this site first" in response.json()["detail"]

    async def test_reports_a_site_it_cannot_reach(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=httpx.ConnectError("refused"))

        response = await logged_in.post(f"/api/sites/{created['id']}/detect")

        assert response.status_code == 502

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/sites/1/detect")).status_code == 401

    async def test_reports_a_deployment_that_cannot_render(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, services
    ) -> None:
        # A browser-mode site is compared through a browser, so a deployment without one cannot
        # answer for it — and must say so rather than failing as an internal error.
        await self.give_it_a_session(db, cipher, created["id"])
        site = await db.get(Site, created["id"])
        site.ping_method = PingMethod.BROWSER
        await db.commit()
        services.settings.browser_enabled = False

        response = await logged_in.post(f"/api/sites/{created['id']}/detect")

        assert response.status_code == 503


class TestTryingRulesOverHttp:
    """Trying rules from the form against the live site."""

    async def give_it_a_session(self, db: AsyncSession, cipher, site_id: int) -> None:
        site = await db.get(Site, site_id)
        site.session = SiteSession(
            state=cipher.encrypt_json(
                {
                    "cookies": [
                        {"name": "session", "value": "v", "domain": "example.org", "path": "/"}
                    ],
                    "origins": [],
                }
            ),
            captured_via=CaptureMethod.IMPORT,
            captured_at=site.created_at,
            cookie_names="session",
        )
        await db.commit()

    def answer(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("cookie"):
            return httpx.Response(200, text="<a>Log out</a>")
        return httpx.Response(200, text="<p>Remember me</p>")

    async def test_reports_rules_that_would_notice_a_dead_session(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        body = (
            await logged_in.post(
                f"/api/sites/{created['id']}/test-rules",
                json={"success_pattern": "Log out", "expected_status": 200},
            )
        ).json()

        assert body["works"] is True
        assert body["live_outcome"] == "ok"
        assert body["dead_outcome"] == "pattern_missing"

    async def test_reports_rules_that_would_not(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        body = (
            await logged_in.post(
                f"/api/sites/{created['id']}/test-rules", json={"expected_status": 200}
            )
        ).json()

        assert body["works"] is False
        assert body["dead_outcome"] == "ok"

    async def test_does_not_save_the_rules_it_was_given(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        # Trying something out must not be a way of applying it.
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        await logged_in.post(
            f"/api/sites/{created['id']}/test-rules", json={"success_pattern": "Log out"}
        )

        await db.refresh(await db.get(Site, created["id"]))
        assert (await db.get(Site, created["id"])).success_pattern == "Logged in as"

    async def test_refuses_without_a_working_session_to_compare_against(
        self, logged_in: httpx.AsyncClient, created: dict
    ) -> None:
        response = await logged_in.post(
            f"/api/sites/{created['id']}/test-rules", json={"success_pattern": "x"}
        )

        assert response.status_code == 409

    async def test_needs_a_login(self, client: httpx.AsyncClient, admin: User) -> None:
        assert (await client.post("/api/sites/1/test-rules", json={})).status_code == 401

    async def test_tries_the_rule_derived_from_the_login_url(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        # A check consults this before anything else, and the trial left it out entirely — so a
        # site whose only working rule was the redirect was told it had nothing.
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        body = (
            await logged_in.post(
                f"/api/sites/{created['id']}/test-rules",
                json={"login_url": "https://example.org/login.php", "expected_status": 200},
            )
        ).json()

        assert [rule["rule"] for rule in body["rules"]] == ["login_url_pattern"]

    async def test_says_that_rule_did_nothing_when_the_site_does_not_redirect(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        body = (
            await logged_in.post(
                f"/api/sites/{created['id']}/test-rules",
                json={"login_url": "https://example.org/login.php", "expected_status": 200},
            )
        ).json()

        assert body["rules"][0]["on_live"] is False
        assert body["rules"][0]["on_dead"] is False
        assert body["rules"][0]["helps"] is False

    async def test_ignores_a_login_url_that_is_the_pinged_page(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, cipher, created: dict, stub
    ) -> None:
        # A rule matching where the ping already finishes would report a dead session for ever, so
        # a check derives nothing from it — and neither should the trial.
        await self.give_it_a_session(db, cipher, created["id"])
        stub.get("https://example.org/home").mock(side_effect=self.answer)

        body = (
            await logged_in.post(
                f"/api/sites/{created['id']}/test-rules",
                json={"login_url": "https://example.org/home", "success_pattern": "Log out"},
            )
        ).json()

        assert [rule["rule"] for rule in body["rules"]] == ["success_pattern"]


class TestShorteningAnInterval:
    """Changing an interval has to change the schedule worked out from the old one."""

    async def schedule(self, db: AsyncSession, site_id: int, *, days: float) -> None:
        site = await db.get(Site, site_id)
        site.last_check_at = datetime.now(UTC)
        site.next_check_at = site.last_check_at + timedelta(days=days)
        await db.commit()

    async def test_brings_the_next_check_forward(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        # The gap being closed: a session expiring before a check that was scheduled under a
        # longer interval, which would otherwise hold for one more full cycle.
        await self.schedule(db, created["id"], days=6.7)

        body = (
            await logged_in.put(
                f"/api/sites/{created['id']}", json={**NEW_SITE, "interval_days": 6}
            )
        ).json()

        site = await db.get(Site, created["id"])
        await db.refresh(site)
        assert site.next_check_at <= site.last_check_at + timedelta(days=6)
        assert body["interval_days"] == 6

    async def test_leaves_it_alone_when_the_interval_grows(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        await self.schedule(db, created["id"], days=5)
        before = (await db.get(Site, created["id"])).next_check_at

        await logged_in.put(f"/api/sites/{created['id']}", json={**NEW_SITE, "interval_days": 30})

        site = await db.get(Site, created["id"])
        await db.refresh(site)
        assert site.next_check_at == before

    async def test_leaves_a_site_that_is_due_now_due_now(
        self, logged_in: httpx.AsyncClient, db: AsyncSession, created: dict
    ) -> None:
        # A newly added site is due immediately; no interval should postpone that.
        await logged_in.put(f"/api/sites/{created['id']}", json={**NEW_SITE, "interval_days": 3})

        site = await db.get(Site, created["id"])
        await db.refresh(site)
        assert site.next_check_at is None
