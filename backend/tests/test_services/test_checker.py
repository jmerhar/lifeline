"""Fetching a site and deciding what the response proved."""

import random
from datetime import UTC, datetime, timedelta

import httpx
import respx

from lifeline.config import Settings
from lifeline.models import CheckOutcome, Site, SiteSession
from lifeline.services.checker import (
    RETRY_BASE,
    HttpFetcher,
    capped_next_check,
    decide,
    is_at_risk,
    matches,
    next_check_time,
    perform_check,
)
from tests.conftest import (
    SAMPLE_STATE,
    StubFetcher,
    make_fetch_result,
    make_settings,
    make_site,
)

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class TestMatches:
    def test_matches_a_plain_substring(self) -> None:
        assert matches("Log out", "<a>Log out</a>") is True

    def test_ignores_case(self) -> None:
        assert matches("log out", "<a>LOG OUT</a>") is True

    def test_matches_a_regex(self) -> None:
        assert matches(r"logged in as \w+", "you are Logged in as jure") is True

    def test_falls_back_to_substring_for_an_invalid_regex(self) -> None:
        # A pasted URL is a common pattern and frequently not valid regex; raising from
        # inside a scheduled check would be a poor trade for strictness.
        assert matches("login.php?redirect=[", "go to /login.php?redirect=[home]") is True

    def test_reports_absence(self) -> None:
        assert matches("Log out", "please sign in") is False


class TestDecide:
    def test_a_good_response_is_ok(self) -> None:
        assert decide(make_site(), make_fetch_result()).outcome is CheckOutcome.OK

    def test_landing_on_the_login_page_means_the_session_is_gone(self) -> None:
        site = make_site(login_url_pattern="login.php")
        result = make_fetch_result(final_url="https://example.org/login.php?returnto=%2Fhome")

        verdict = decide(site, result)

        assert verdict.outcome is CheckOutcome.LOGIN_EXPIRED
        assert "login page" in verdict.detail

    def test_the_login_redirect_is_judged_before_the_status_code(self) -> None:
        # The two rules have to be able to disagree for this to test anything: the response
        # both lands on the login page and carries a status the site does not expect. Judged
        # in the other order it would be reported as the site being broken, which sends you
        # looking at the site instead of at the session that has actually gone.
        site = make_site(login_url_pattern="login.php", expected_status=200)
        result = make_fetch_result(final_url="https://example.org/login.php", status_code=403)

        assert decide(site, result).outcome is CheckOutcome.LOGIN_EXPIRED

    def test_an_unexpected_status_is_an_http_error(self) -> None:
        verdict = decide(make_site(), make_fetch_result(status_code=503))

        assert verdict.outcome is CheckOutcome.HTTP_ERROR
        assert "got 503" in verdict.detail

    def test_a_site_can_expect_a_status_other_than_200(self) -> None:
        site = make_site(expected_status=302, follow_redirects=False)

        assert decide(site, make_fetch_result(status_code=302)).outcome is CheckOutcome.OK

    def test_a_logged_out_marker_means_the_session_is_gone(self) -> None:
        site = make_site(failure_pattern="Enter your password")
        result = make_fetch_result(body="<form>Enter your password</form>")

        verdict = decide(site, result)

        assert verdict.outcome is CheckOutcome.LOGIN_EXPIRED
        assert "only appears when logged out" in verdict.detail

    def test_a_missing_success_marker_is_reported_separately(self) -> None:
        site = make_site(success_pattern="Logged in as")
        result = make_fetch_result(body="<html>something else entirely</html>")

        verdict = decide(site, result)

        assert verdict.outcome is CheckOutcome.PATTERN_MISSING
        assert "does not contain" in verdict.detail

    def test_a_present_success_marker_passes(self) -> None:
        site = make_site(success_pattern="Logged in as")

        assert decide(site, make_fetch_result()).outcome is CheckOutcome.OK

    def test_the_failure_marker_wins_over_a_present_success_marker(self) -> None:
        site = make_site(success_pattern="Log out", failure_pattern="session expired")
        result = make_fetch_result(body="session expired. Log out")

        assert decide(site, result).outcome is CheckOutcome.LOGIN_EXPIRED


class TestNextCheckTime:
    def test_a_successful_check_waits_the_full_interval(self) -> None:
        site = make_site(interval_days=7, jitter_percent=0)

        assert next_check_time(site, CheckOutcome.OK, now=NOW) == NOW + timedelta(days=7)

    def test_a_lapsed_session_is_not_retried_sooner(self) -> None:
        # Asking again does not revive a dead session, and the site is entitled to object
        # to being asked more often than the account needs.
        site = make_site(interval_days=7, jitter_percent=0)

        expected = NOW + timedelta(days=7)
        assert next_check_time(site, CheckOutcome.LOGIN_EXPIRED, now=NOW) == expected

    def test_jitter_stays_within_the_configured_band(self) -> None:
        site = make_site(interval_days=10, jitter_percent=20)
        rng = random.Random(0)

        times = [next_check_time(site, CheckOutcome.OK, now=NOW, rng=rng) for _ in range(200)]

        assert all(NOW + timedelta(days=8) <= t <= NOW + timedelta(days=12) for t in times)
        # And it must actually vary, or it is not jitter.
        assert len(set(times)) > 1

    def test_zero_jitter_is_exact(self) -> None:
        site = make_site(interval_days=3, jitter_percent=0)
        rng = random.Random(1)

        assert next_check_time(site, CheckOutcome.OK, now=NOW, rng=rng) == NOW + timedelta(days=3)

    def test_a_first_failure_retries_in_minutes(self) -> None:
        site = make_site(consecutive_failures=1)

        assert next_check_time(site, CheckOutcome.NETWORK_ERROR, now=NOW) == NOW + RETRY_BASE

    def test_the_retry_delay_grows_with_consecutive_failures(self) -> None:
        first = next_check_time(make_site(consecutive_failures=1), CheckOutcome.HTTP_ERROR, now=NOW)
        second = next_check_time(
            make_site(consecutive_failures=2), CheckOutcome.HTTP_ERROR, now=NOW
        )

        assert second > first

    def test_the_retry_delay_never_exceeds_the_interval(self) -> None:
        site = make_site(interval_days=1, consecutive_failures=20)

        result = next_check_time(site, CheckOutcome.NETWORK_ERROR, now=NOW)

        assert result == NOW + timedelta(days=1)


class TestHttpFetcher:
    @respx.mock
    async def test_sends_the_stored_session_and_the_captured_user_agent(
        self, settings: Settings
    ) -> None:
        route = respx.get("https://example.org/home").respond(200, text="hello")
        site = make_site(user_agent="CapturedAgent/1.0")

        result = await HttpFetcher(settings).fetch(site, SAMPLE_STATE, accept_language="en")

        request = route.calls.last.request
        # The captured agent must be replayed verbatim: a Cloudflare clearance cookie is
        # bound to the agent that earned it.
        assert request.headers["user-agent"] == "CapturedAgent/1.0"
        assert request.headers["cookie"] == "session=abc"
        assert result.status_code == 200
        assert result.body == "hello"

    @respx.mock
    async def test_falls_back_to_the_default_user_agent(self, settings: Settings) -> None:
        route = respx.get("https://example.org/home").respond(200)

        await HttpFetcher(settings).fetch(make_site(
            user_agent=None), SAMPLE_STATE, accept_language="en"
        )

        assert route.calls.last.request.headers["user-agent"] == settings.default_user_agent

    @respx.mock
    async def test_reports_the_final_url_after_redirects(self, settings: Settings) -> None:
        respx.get("https://example.org/home").respond(
            302, headers={"location": "https://example.org/login.php"}
        )
        respx.get("https://example.org/login.php").respond(200, text="sign in")

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE, accept_language="en")

        assert result.final_url == "https://example.org/login.php"

    @respx.mock
    async def test_does_not_follow_redirects_when_the_site_says_not_to(
        self, settings: Settings
    ) -> None:
        respx.get("https://example.org/home").respond(
            302, headers={"location": "https://example.org/login.php"}
        )

        result = await HttpFetcher(settings).fetch(make_site(
            follow_redirects=False), SAMPLE_STATE, accept_language="en"
        )

        assert result.status_code == 302
        assert result.final_url == "https://example.org/home"

    @respx.mock
    async def test_brings_back_a_rotated_cookie(self, settings: Settings) -> None:
        respx.get("https://example.org/home").respond(
            200, headers={"set-cookie": "session=rotated; Domain=.example.org; Path=/; Secure"}
        )

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE, accept_language="en")

        assert result.rotated is True
        assert result.state["cookies"][0]["value"] == "rotated"

    @respx.mock
    async def test_truncates_an_enormous_body(self, settings: Settings) -> None:
        from lifeline.services.checker import MAX_BODY_CHARS

        respx.get("https://example.org/home").respond(200, text="x" * (MAX_BODY_CHARS + 500))

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE, accept_language="en")

        assert len(result.body) == MAX_BODY_CHARS


class TestPerformCheck:
    async def test_a_site_with_no_session_is_reported_as_lapsed(self) -> None:
        # Nothing is wrong with the site or the network; someone has to log in.
        report = await perform_check(
            make_site(), None, StubFetcher(make_fetch_result()), accept_language="en"
        )

        assert report.verdict.outcome is CheckOutcome.LOGIN_EXPIRED
        assert "no session" in report.verdict.detail
        assert report.state is None

    async def test_a_network_failure_leaves_the_session_untouched(self) -> None:
        fetcher = StubFetcher(httpx.ConnectTimeout("timed out"))

        report = await perform_check(make_site(), SAMPLE_STATE, fetcher, accept_language="en")

        assert report.verdict.outcome is CheckOutcome.NETWORK_ERROR
        assert "ConnectTimeout" in report.verdict.detail
        # No state to persist: the session was never rejected, so it must not be replaced.
        assert report.state is None
        assert report.rotated is False

    async def test_a_successful_check_returns_the_merged_state(self) -> None:
        fetcher = StubFetcher(make_fetch_result(rotated=True))

        report = await perform_check(make_site(), SAMPLE_STATE, fetcher, accept_language="en")

        assert report.verdict.outcome is CheckOutcome.OK
        assert report.rotated is True
        assert report.state == SAMPLE_STATE

    async def test_records_how_long_the_check_took(self) -> None:
        report = await perform_check(
            make_site(), SAMPLE_STATE, StubFetcher(make_fetch_result()), accept_language="en"
        )

        assert report.duration_ms >= 0


class TestIsAtRisk:
    """A clock running out only matters if no check will reset it first."""

    def test_says_nothing_when_no_deadline_is_known(self) -> None:
        assert is_at_risk(make_site(), make_settings(), now=NOW) is None

    def test_warns_when_the_deadline_falls_before_the_next_check(self) -> None:
        # The case worth raising: the interval is longer than the site tolerates, so nothing will
        # touch this site before its own clock runs out.
        site = make_site(
            inactivity_limit_days=90,
            last_ok_at=NOW - timedelta(days=85),
            next_check_at=NOW + timedelta(days=7),
        )

        reason = is_at_risk(site, make_settings(warning_lead_days=7), now=NOW)

        assert reason is not None
        assert "5 day(s)" in reason
        assert "before the next check" in reason

    def test_stays_quiet_when_a_check_comes_first(self) -> None:
        # A successful check is activity, so it moves the deadline. Warning about a deadline we are
        # going to reset before it arrives is noise.
        site = make_site(
            inactivity_limit_days=90,
            last_ok_at=NOW - timedelta(days=85),
            next_check_at=NOW + timedelta(days=1),
        )

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is None

    def test_stays_quiet_while_the_deadline_is_far_off(self) -> None:
        site = make_site(
            inactivity_limit_days=90,
            last_ok_at=NOW - timedelta(days=10),
            next_check_at=NOW + timedelta(days=365),
        )

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is None

    def test_measures_the_deadline_from_the_last_success(self) -> None:
        # A failing check must not look like activity, or the tool hides the very situation it
        # exists to catch.
        site = make_site(
            inactivity_limit_days=30,
            last_ok_at=NOW - timedelta(days=28),
            last_check_at=NOW,
            next_check_at=NOW + timedelta(days=7),
        )

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is not None

    def test_reports_zero_days_rather_than_a_negative_countdown(self) -> None:
        site = make_site(
            inactivity_limit_days=30,
            last_ok_at=NOW - timedelta(days=45),
            next_check_at=NOW + timedelta(days=7),
        )

        assert "0 day(s)" in is_at_risk(site, make_settings(), now=NOW)

    def test_warns_when_everything_stored_expires_before_the_next_check(self) -> None:
        site = make_site(next_check_at=NOW + timedelta(days=30))
        site.session = SiteSession(expires_at=NOW + timedelta(days=3), state=b"")

        reason = is_at_risk(site, make_settings(warning_lead_days=7), now=NOW)

        assert reason is not None
        assert "expires in 3 day(s)" in reason

    def test_stays_quiet_when_a_check_will_reissue_it_first(self) -> None:
        # This is what a fifteen-minute analytics cookie used to trigger, on a site whose session
        # was fine and being reissued on every ping.
        site = make_site(next_check_at=NOW + timedelta(hours=1))
        site.session = SiteSession(expires_at=NOW + timedelta(days=3), state=b"")

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is None

    def test_stays_quiet_for_an_expiry_further_off_than_the_warning(self) -> None:
        site = make_site(next_check_at=NOW + timedelta(days=365))
        site.session = SiteSession(expires_at=NOW + timedelta(days=60), state=b"")

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is None

    def test_ignores_a_session_with_no_recorded_expiry(self) -> None:
        # The usual case for a pure session cookie: it lasts until the site says otherwise, and no
        # date here could predict that.
        site = make_site(next_check_at=NOW + timedelta(days=30))
        site.session = SiteSession(expires_at=None, state=b"")

        assert is_at_risk(site, make_settings(), now=NOW) is None

    def test_stays_quiet_when_a_check_is_due_immediately(self) -> None:
        # No next-check time means due now, not "never" — the check about to run will either reset
        # the clock or report the session as gone.
        site = make_site(next_check_at=None)
        site.session = SiteSession(expires_at=NOW + timedelta(days=2), state=b"")

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is None

    def test_warns_when_the_next_check_is_itself_overdue(self) -> None:
        # A next check in the past is not a check that is going to happen: it is one nothing has
        # run, because the site was paused or the schedule stopped. Its clocks still run out, and
        # this is exactly when nobody is watching.
        site = make_site(next_check_at=NOW - timedelta(days=3))
        site.session = SiteSession(expires_at=NOW + timedelta(days=2), state=b"")

        reason = is_at_risk(site, make_settings(warning_lead_days=7), now=NOW)

        assert reason is not None
        assert "expires in 2 day(s)" in reason

    def test_warns_about_a_deadline_already_passed(self) -> None:
        # Overdue is the loudest case there is; it must not fall through as "nothing to say".
        site = make_site(next_check_at=NOW - timedelta(days=3), inactivity_limit_days=90)
        site.last_ok_at = NOW - timedelta(days=95)

        assert is_at_risk(site, make_settings(warning_lead_days=7), now=NOW) is not None


class TestTheDerivedLoginUrlRule:
    """Landing on the login page is worked out from the login URL, not asked for separately."""

    def test_a_ping_that_ends_on_the_login_page_is_a_dead_session(self) -> None:
        site = make_site(
            ping_url="https://example.org/browse", login_url="https://example.org/auth/signin"
        )

        verdict = decide(site, make_fetch_result(final_url="https://example.org/auth/signin"))

        assert verdict.outcome is CheckOutcome.LOGIN_EXPIRED

    def test_ignores_the_query_a_redirect_adds(self) -> None:
        site = make_site(
            ping_url="https://example.org/browse", login_url="https://example.org/login.php"
        )

        verdict = decide(
            site, make_fetch_result(final_url="https://example.org/login.php?return=%2Fbrowse")
        )

        assert verdict.outcome is CheckOutcome.LOGIN_EXPIRED

    def test_says_nothing_for_a_site_that_does_not_redirect(self) -> None:
        # The ping finishes where it started, which is the common case, and the rule is inert.
        site = make_site(ping_url="https://example.org/", login_url="https://example.org/login.php")

        verdict = decide(site, make_fetch_result(final_url="https://example.org/"))

        assert verdict.outcome is CheckOutcome.OK

    def test_never_derives_a_rule_matching_the_pinged_page(self) -> None:
        # A login URL that is the page being pinged would otherwise report a dead session on
        # every check, for ever.
        site = make_site(ping_url="https://example.org/in", login_url="https://example.org/in")

        assert site.effective_login_url_pattern is None
        assert decide(site, make_fetch_result(final_url="https://example.org/in")).outcome is (
            CheckOutcome.OK
        )

    def test_derives_nothing_without_a_login_url(self) -> None:
        assert make_site(login_url=None).effective_login_url_pattern is None

    def test_means_the_path_and_not_a_pattern_resembling_it(self) -> None:
        # "login.php" read as a regex matches "loginXphp" as well; the derived form does not.
        site = make_site(
            ping_url="https://example.org/browse", login_url="https://example.org/login.php"
        )

        verdict = decide(site, make_fetch_result(final_url="https://example.org/loginXphp"))

        assert verdict.outcome is CheckOutcome.OK

    def test_a_stored_pattern_overrides_the_derived_one(self) -> None:
        # For a site that sends a signed-out request somewhere other than its login page.
        site = make_site(
            ping_url="https://example.org/browse",
            login_url="https://example.org/login.php",
            login_url_pattern="session-expired",
        )

        assert site.effective_login_url_pattern == "session-expired"
        assert decide(
            site, make_fetch_result(final_url="https://example.org/session-expired")
        ).outcome is CheckOutcome.LOGIN_EXPIRED


class TestJitterNeverDelaysACheck:
    """An interval is the longest anyone is willing to wait, not an average to scatter around."""

    def spread(self, site: Site, draws: int = 200) -> list[datetime]:
        return [
            next_check_time(site, CheckOutcome.OK, now=NOW, rng=random.Random(seed))
            for seed in range(draws)
        ]

    def test_never_schedules_beyond_the_interval(self) -> None:
        site = make_site(interval_days=7, jitter_percent=10)

        assert all(when <= NOW + timedelta(days=7) for when in self.spread(site))

    def test_still_spreads_them_out(self) -> None:
        # The point of jitter: not every site asked at the same clock time for years.
        site = make_site(interval_days=7, jitter_percent=10)

        assert len(set(self.spread(site))) > 100

    def test_stays_within_the_percentage_asked_for(self) -> None:
        site = make_site(interval_days=10, jitter_percent=10)

        assert all(when >= NOW + timedelta(days=9) for when in self.spread(site))

    def test_no_jitter_means_exactly_the_interval(self) -> None:
        site = make_site(interval_days=7, jitter_percent=0)

        assert next_check_time(site, CheckOutcome.OK, now=NOW) == NOW + timedelta(days=7)

    def test_a_session_lasting_exactly_the_interval_is_never_missed(self) -> None:
        # The case that sent a warning the moment a site was added: a seven-day session, checked
        # every seven days, and a check jittered five hours late landing after it had gone.
        settings_row = make_settings(warning_lead_days=7)
        for seed in range(200):
            site = make_site(interval_days=7, jitter_percent=10)
            site.session = SiteSession(expires_at=NOW + timedelta(days=7), state=b"")
            site.next_check_at = next_check_time(
                site, CheckOutcome.OK, now=NOW, rng=random.Random(seed)
            )

            assert is_at_risk(site, settings_row, now=NOW) is None


class TestCountingTheDaysLeft:
    def test_rounds_rather_than_truncates(self) -> None:
        # Six hours short of a week is a seven-day session, which is what the site granting it
        # says; calling it six invites somebody to check the arithmetic instead of the interval.
        site = make_site(interval_days=30, next_check_at=NOW + timedelta(days=30))
        site.session = SiteSession(expires_at=NOW + timedelta(days=7, hours=-6), state=b"")

        reason = is_at_risk(site, make_settings(warning_lead_days=14), now=NOW)

        assert "7 day(s)" in reason

    def test_never_reports_a_negative_count(self) -> None:
        site = make_site(interval_days=30, next_check_at=NOW + timedelta(days=30))
        site.session = SiteSession(expires_at=NOW - timedelta(days=3), state=b"")

        reason = is_at_risk(site, make_settings(warning_lead_days=7), now=NOW)

        assert "0 day(s)" in reason


class TestTheLanguageAskedFor:
    """What a site is told about the language it should answer in."""

    @respx.mock
    async def test_asks_for_the_configured_language(self, settings: Settings) -> None:
        # A site serving more than one decides from this. Without it, a page somebody reads in
        # English arrives in whatever the site prefers — taking every pattern they typed with it.
        route = respx.get("https://example.org/home").respond(200, text="ok")

        await HttpFetcher(settings).fetch(
            make_site(), SAMPLE_STATE, accept_language="hu-HU,hu;q=0.9"
        )

        assert route.calls.last.request.headers["Accept-Language"] == "hu-HU,hu;q=0.9"

    @respx.mock
    async def test_asks_alongside_the_captured_user_agent(self, settings: Settings) -> None:
        route = respx.get("https://example.org/home").respond(200, text="ok")

        await HttpFetcher(settings).fetch(
            make_site(user_agent="Captured/1"), SAMPLE_STATE, accept_language="en-GB"
        )

        assert route.calls.last.request.headers["User-Agent"] == "Captured/1"
        assert route.calls.last.request.headers["Accept-Language"] == "en-GB"


class TestCappingTheScheduleToTheInterval:
    """A stored next check, once the interval it was worked out from has changed."""

    def test_pulls_a_check_in_when_the_interval_shortens(self) -> None:
        # The gap somebody shortening an interval is trying to close; leaving it would hold that
        # gap for one more full cycle.
        site = make_site(interval_days=6)
        site.last_check_at = NOW
        site.next_check_at = NOW + timedelta(days=6, hours=16)

        assert capped_next_check(site, now=NOW) == NOW + timedelta(days=6)

    def test_leaves_a_check_alone_when_the_interval_lengthens(self) -> None:
        # It was already agreed to, and pushing it back is how a check lands after the session it
        # was meant to renew.
        site = make_site(interval_days=30)
        site.last_check_at = NOW
        site.next_check_at = NOW + timedelta(days=5)

        assert capped_next_check(site, now=NOW) == NOW + timedelta(days=5)

    def test_leaves_a_check_that_already_fits(self) -> None:
        site = make_site(interval_days=7)
        site.last_check_at = NOW
        site.next_check_at = NOW + timedelta(days=6, hours=16)

        assert capped_next_check(site, now=NOW) == NOW + timedelta(days=6, hours=16)

    def test_measures_from_now_for_a_site_never_checked(self) -> None:
        site = make_site(interval_days=3)
        site.last_check_at = None
        site.next_check_at = NOW + timedelta(days=10)

        assert capped_next_check(site, now=NOW) == NOW + timedelta(days=3)

    def test_leaves_a_site_that_is_due_now_due_now(self) -> None:
        # No next-check time means due immediately, which no interval should postpone.
        site = make_site(interval_days=1, next_check_at=None)

        assert capped_next_check(site, now=NOW) is None
