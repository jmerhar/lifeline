"""Fetching a site and deciding what the response proved."""

import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from lifeline.config import Settings
from lifeline.models import CheckOutcome, SiteSession
from lifeline.services.checker import (
    RETRY_BASE,
    HttpFetcher,
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
        second = next_check_time(make_site(consecutive_failures=2), CheckOutcome.HTTP_ERROR, now=NOW)

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

        result = await HttpFetcher(settings).fetch(site, SAMPLE_STATE)

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

        await HttpFetcher(settings).fetch(make_site(user_agent=None), SAMPLE_STATE)

        assert route.calls.last.request.headers["user-agent"] == settings.default_user_agent

    @respx.mock
    async def test_reports_the_final_url_after_redirects(self, settings: Settings) -> None:
        respx.get("https://example.org/home").respond(
            302, headers={"location": "https://example.org/login.php"}
        )
        respx.get("https://example.org/login.php").respond(200, text="sign in")

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE)

        assert result.final_url == "https://example.org/login.php"

    @respx.mock
    async def test_does_not_follow_redirects_when_the_site_says_not_to(
        self, settings: Settings
    ) -> None:
        respx.get("https://example.org/home").respond(
            302, headers={"location": "https://example.org/login.php"}
        )

        result = await HttpFetcher(settings).fetch(make_site(follow_redirects=False), SAMPLE_STATE)

        assert result.status_code == 302
        assert result.final_url == "https://example.org/home"

    @respx.mock
    async def test_brings_back_a_rotated_cookie(self, settings: Settings) -> None:
        respx.get("https://example.org/home").respond(
            200, headers={"set-cookie": "session=rotated; Domain=.example.org; Path=/; Secure"}
        )

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE)

        assert result.rotated is True
        assert result.state["cookies"][0]["value"] == "rotated"

    @respx.mock
    async def test_truncates_an_enormous_body(self, settings: Settings) -> None:
        from lifeline.services.checker import MAX_BODY_CHARS

        respx.get("https://example.org/home").respond(200, text="x" * (MAX_BODY_CHARS + 500))

        result = await HttpFetcher(settings).fetch(make_site(), SAMPLE_STATE)

        assert len(result.body) == MAX_BODY_CHARS


class TestPerformCheck:
    async def test_a_site_with_no_session_is_reported_as_lapsed(self) -> None:
        # Nothing is wrong with the site or the network; someone has to log in.
        report = await perform_check(make_site(), None, StubFetcher(make_fetch_result()))

        assert report.verdict.outcome is CheckOutcome.LOGIN_EXPIRED
        assert "no session" in report.verdict.detail
        assert report.state is None

    async def test_a_network_failure_leaves_the_session_untouched(self) -> None:
        fetcher = StubFetcher(httpx.ConnectTimeout("timed out"))

        report = await perform_check(make_site(), SAMPLE_STATE, fetcher)

        assert report.verdict.outcome is CheckOutcome.NETWORK_ERROR
        assert "ConnectTimeout" in report.verdict.detail
        # No state to persist: the session was never rejected, so it must not be replaced.
        assert report.state is None
        assert report.rotated is False

    async def test_a_successful_check_returns_the_merged_state(self) -> None:
        fetcher = StubFetcher(make_fetch_result(rotated=True))

        report = await perform_check(make_site(), SAMPLE_STATE, fetcher)

        assert report.verdict.outcome is CheckOutcome.OK
        assert report.rotated is True
        assert report.state == SAMPLE_STATE

    async def test_records_how_long_the_check_took(self) -> None:
        report = await perform_check(make_site(), SAMPLE_STATE, StubFetcher(make_fetch_result()))

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

    def test_warns_about_a_site_nothing_is_going_to_check(self) -> None:
        # No next check at all — a disabled site. Its clocks still run out.
        site = make_site(next_check_at=None)
        site.session = SiteSession(expires_at=NOW + timedelta(days=2), state=b"")

        reason = is_at_risk(site, make_settings(warning_lead_days=7), now=NOW)

        assert reason is not None
        assert "is due" in reason
