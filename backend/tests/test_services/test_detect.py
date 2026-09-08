"""Working out a site's rules by fetching it signed in and signed out."""

import httpx
import pytest
import respx

from lifeline.models import CheckOutcome, PingMethod, Site
from lifeline.services.browser.manager import BrowserUnavailable
from lifeline.services.detect import Detected, Detector, Probe, compare, verify
from tests.conftest import SAMPLE_STATE, make_site

SIGNED_IN = "<html><body>Welcome back. <a href='/logout'>Log out</a></body></html>"
SIGNED_OUT = "<html><body><form>Enter your password <label>Remember me</label></form></body></html>"


def probe(body: str, *, url: str = "https://example.org/home", status: int = 200) -> Probe:
    return Probe(status_code=status, final_url=url, body=body)


class TestTheRedirectSignal:
    def test_takes_the_last_path_segment_of_where_it_landed(self) -> None:
        found = compare(
            probe(SIGNED_IN),
            probe(SIGNED_OUT, url="https://example.org/login.php?return=%2Fhome"),
        )

        assert found.login_url_pattern == "login.php"

    def test_says_why_in_a_sentence_someone_can_read(self) -> None:
        found = compare(probe(SIGNED_IN), probe(SIGNED_OUT, url="https://example.org/login.php"))

        assert any("ends at https://example.org/login.php" in note for note in found.notes)

    def test_falls_back_to_the_path_when_the_segment_is_shared(self) -> None:
        # Both end at .../index.php, distinguished only by the directory.
        found = compare(
            probe(SIGNED_IN, url="https://example.org/members/index.php"),
            probe(SIGNED_OUT, url="https://example.org/account/index.php"),
        )

        assert found.login_url_pattern == "/account/index.php"

    def test_falls_back_to_the_whole_url_when_only_the_query_differs(self) -> None:
        found = compare(
            probe(SIGNED_IN, url="https://example.org/home"),
            probe(SIGNED_OUT, url="https://example.org/home?next=login"),
        )

        assert found.login_url_pattern == "https://example.org/home?next=login"

    def test_says_nothing_when_both_land_in_the_same_place(self) -> None:
        found = compare(probe(SIGNED_IN), probe(SIGNED_OUT))

        assert found.login_url_pattern is None


class TestTheTextSignals:
    def test_finds_what_only_a_signed_in_page_says(self) -> None:
        found = compare(probe(SIGNED_IN), probe(SIGNED_OUT))

        assert found.success_pattern == "Log out"

    def test_finds_what_only_a_signed_out_page_says(self) -> None:
        found = compare(probe(SIGNED_IN), probe(SIGNED_OUT))

        assert found.failure_pattern == "Remember me"

    def test_skips_a_signed_out_phrase_that_is_on_both_pages(self) -> None:
        # "Remember me" would be chosen first, but a site that carries it in a footer on every
        # page says nothing by carrying it — so the next candidate that really does differ wins.
        both = "<footer>Remember me why you are here</footer>"
        found = compare(probe(SIGNED_IN + both), probe("<p>Please Sign in</p>" + both))

        assert found.failure_pattern == "Sign in"

    def test_skips_a_signed_in_phrase_that_is_on_both_pages(self) -> None:
        # The same trap the other way round: a "Log out" link left in the markup of a login page.
        both = "<nav>Log out</nav>"
        found = compare(probe("<p>My account</p>" + both), probe(SIGNED_OUT + both))

        assert found.success_pattern == "My account"

    def test_matches_whatever_case_the_page_uses(self) -> None:
        found = compare(probe("<a>LOG OUT</a>"), probe("<p>please sign in</p>"))

        assert found.success_pattern == "Log out"

    def test_reports_nothing_it_could_not_find(self) -> None:
        found = compare(probe("<p>a page</p>"), probe("<p>another page</p>"))

        assert found.success_pattern is None
        assert found.failure_pattern is None
        assert found.found_anything is False

    def test_explains_what_to_do_when_the_pages_look_alike(self) -> None:
        found = compare(probe("<p>same</p>"), probe("<p>same</p>"))

        assert any("looks the same" in note for note in found.notes)


class TestTheStatusSignal:
    def test_mentions_a_differing_status_without_changing_the_expected_one(self) -> None:
        # Reported rather than applied: the expected status is the person's to set, and a site
        # that answers 403 to a signed-out request may answer 500 to a broken one.
        found = compare(probe(SIGNED_IN), probe("", status=403))

        assert any("HTTP 403" in note for note in found.notes)


class TestFetching:
    @respx.mock
    async def test_fetches_once_with_the_session_and_once_without(self, settings) -> None:
        seen: list[str | None] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("cookie"))
            body = SIGNED_IN if request.headers.get("cookie") else SIGNED_OUT
            return httpx.Response(200, text=body)

        respx.get("https://example.org/home").mock(side_effect=record)

        found = await Detector(settings).detect(make_site(), SAMPLE_STATE)

        assert len(seen) == 2
        assert seen[0] is not None
        assert seen[1] is None
        assert found.success_pattern == "Log out"

    @respx.mock
    async def test_follows_a_redirect_even_when_the_site_says_not_to(self, settings) -> None:
        # The site's own setting exists so a check can judge a 302 as the answer. Here the whole
        # point is to see where a signed-out request ends up, which a stopped redirect hides.
        respx.get("https://example.org/home").mock(
            return_value=httpx.Response(302, headers={"Location": "https://example.org/login.php"})
        )
        respx.get("https://example.org/login.php").mock(
            return_value=httpx.Response(200, text=SIGNED_OUT)
        )

        result = await Detector(settings).probe(
            make_site(follow_redirects=False), SAMPLE_STATE
        )

        assert result.final_url == "https://example.org/login.php"



class TestTheLoginUrl:
    """Where a signed-out request lands is the site's login page, by definition."""

    def test_reports_where_a_signed_out_request_ended_up(self) -> None:
        found = compare(probe(SIGNED_IN), probe(SIGNED_OUT, url="https://example.org/login.php"))

        assert found.login_url == "https://example.org/login.php"

    def test_drops_the_return_parameter(self) -> None:
        # Kept, it would be stored as the place to open a browser for every future login,
        # sending it back to one particular page for reasons nobody would remember.
        found = compare(
            probe(SIGNED_IN),
            probe(SIGNED_OUT, url="https://example.org/login.php?return=%2Fhome#top"),
        )

        assert found.login_url == "https://example.org/login.php"

    def test_reports_nothing_when_the_request_did_not_move(self) -> None:
        assert compare(probe(SIGNED_IN), probe(SIGNED_OUT)).login_url is None

    def test_is_not_on_its_own_a_way_to_judge_a_page(self) -> None:
        # It says where to open a browser, not how to tell a live session from a dead one.
        # Asserted on the value directly: a redirect always yields a pattern as well, so no pair
        # of pages produces this state — the distinction is in what the property counts.
        assert Detected(login_url="https://example.org/login").found_anything is False


class TestABrowserRenderedSite:
    """A site that builds its page in the browser has to be compared the same way.

    Its server sends the same markup signed in or out — the difference appears only once the
    JavaScript has run — so comparing plain responses reports, correctly and uselessly, that the
    two are identical.
    """

    @respx.mock
    async def test_finds_a_difference_a_plain_response_would_not_show(
        self, settings, browser, fake_driver
    ) -> None:
        # The server's own answer is the same either way — an empty shell — so a comparison that
        # read it would report "the page looks the same" and leave nothing to check with.
        shell = "<html><div id='app'></div></html>"
        respx.get("https://example.org/home").mock(return_value=httpx.Response(200, text=shell))
        site = make_site(ping_method=PingMethod.BROWSER)

        found = await Detector(settings, browser).detect(site, SAMPLE_STATE)

        assert fake_driver.fetched == ["https://example.org/home"] * 2
        assert found.success_pattern == "Log out"
        assert found.failure_pattern == "Remember me"

    @respx.mock
    async def test_a_plain_comparison_of_the_same_site_finds_nothing(
        self, settings, browser
    ) -> None:
        # The other half of the point: left as an HTTP site, this is what the person saw.
        shell = "<html><div id='app'></div></html>"
        respx.get("https://example.org/home").mock(return_value=httpx.Response(200, text=shell))

        found = await Detector(settings, browser).detect(make_site(), SAMPLE_STATE)

        assert found.found_anything is False

    async def test_asks_the_browser_twice_with_and_without_the_session(
        self, settings, browser, fake_driver
    ) -> None:
        await Detector(settings, browser).probe(
            make_site(ping_method=PingMethod.BROWSER), SAMPLE_STATE
        )
        await Detector(settings, browser).probe(make_site(ping_method=PingMethod.BROWSER), None)

        assert len(fake_driver.fetched) == 2

    async def test_says_so_when_the_deployment_cannot_render(self, settings) -> None:
        # A detector with no browser behind it must not silently fall back to a plain fetch,
        # which is what made the comparison useless for this kind of site.
        with pytest.raises(BrowserUnavailable):
            await Detector(settings).probe(make_site(ping_method=PingMethod.BROWSER), SAMPLE_STATE)


class TestTryingRulesOut:
    """Whether a set of rules would notice a dead session, judged by the code that judges checks."""

    def rules(self, **overrides: object) -> Site:
        values: dict[str, object] = {
            "login_url_pattern": None,
            "success_pattern": None,
            "failure_pattern": None,
            "expected_status": 200,
            "follow_redirects": True,
        }
        values.update(overrides)
        return make_site(**values)

    def test_a_success_pattern_that_only_the_live_page_has_works(self) -> None:
        trial = verify(self.rules(success_pattern="Log out"), probe(SIGNED_IN), probe(SIGNED_OUT))

        assert trial.works is True
        assert trial.live_outcome is CheckOutcome.OK
        assert trial.dead_outcome is CheckOutcome.PATTERN_MISSING

    def test_a_failure_pattern_that_only_the_dead_page_has_works(self) -> None:
        trial = verify(
            self.rules(failure_pattern="Remember me"), probe(SIGNED_IN), probe(SIGNED_OUT)
        )

        assert trial.works is True
        assert trial.dead_outcome is CheckOutcome.LOGIN_EXPIRED

    def test_rules_that_pass_both_pages_do_not_work(self) -> None:
        # The dangerous case: a site configured this way never reports a problem, and looks
        # configured while doing it.
        trial = verify(self.rules(success_pattern="html"), probe(SIGNED_IN), probe(SIGNED_OUT))

        assert trial.live_outcome is CheckOutcome.OK
        assert trial.dead_outcome is CheckOutcome.OK
        assert trial.works is False

    def test_rules_that_fail_the_live_page_do_not_work(self) -> None:
        # The other way round: a problem reported constantly, which is at least loud.
        trial = verify(
            self.rules(success_pattern="Not on either page"), probe(SIGNED_IN), probe(SIGNED_OUT)
        )

        assert trial.live_outcome is CheckOutcome.PATTERN_MISSING
        assert trial.works is False

    def test_no_rules_at_all_do_not_work(self) -> None:
        trial = verify(self.rules(), probe(SIGNED_IN), probe(SIGNED_OUT))

        assert trial.live_outcome is CheckOutcome.OK
        assert trial.dead_outcome is CheckOutcome.OK
        assert trial.works is False

    def test_a_login_pattern_matching_both_urls_does_not_work(self) -> None:
        # It would report a live session as dead, which is why the pattern is tried against the
        # signed-in page too rather than only against the one it is meant to catch.
        trial = verify(
            self.rules(login_url_pattern="example.org"),
            probe(SIGNED_IN),
            probe(SIGNED_OUT, url="https://example.org/login.php"),
        )

        assert trial.live_outcome is CheckOutcome.LOGIN_EXPIRED
        assert trial.works is False

    def test_explains_each_verdict(self) -> None:
        trial = verify(self.rules(success_pattern="Log out"), probe(SIGNED_IN), probe(SIGNED_OUT))

        assert trial.dead_detail is not None
        assert "Log out" in trial.dead_detail


class TestWhatEachRuleDid:
    """A verdict stops at the first rule that fires, so each is reported on its own too."""

    def rules(self, **overrides: object) -> Site:
        values: dict[str, object] = {
            "login_url_pattern": None,
            "success_pattern": None,
            "failure_pattern": None,
            "expected_status": 200,
            "follow_redirects": True,
        }
        values.update(overrides)
        return make_site(**values)

    def test_names_a_rule_that_matched_nothing(self) -> None:
        # The case that looked identical to a working rule: the verdict came from a later one, so
        # nothing said this had never matched at all.
        site = self.rules(login_url_pattern="login.php", success_pattern="Log out")
        trial = verify(site, probe(SIGNED_IN), probe(SIGNED_OUT))

        pattern = next(rule for rule in trial.rules if rule.rule == "login_url_pattern")
        assert pattern.on_live is False
        assert pattern.on_dead is False
        assert pattern.helps is False

    def test_reports_a_rule_further_down_the_order_that_does_work(self) -> None:
        site = self.rules(login_url_pattern="login.php", success_pattern="Log out")
        trial = verify(site, probe(SIGNED_IN), probe(SIGNED_OUT))

        success = next(rule for rule in trial.rules if rule.rule == "success_pattern")
        assert success.on_live is True
        assert success.on_dead is False
        assert success.helps is True

    def test_flags_a_rule_that_fires_on_the_live_page_too(self) -> None:
        # A pattern loose enough to match both would report a working session as dead.
        site = self.rules(login_url_pattern="example.org")
        trial = verify(
            site, probe(SIGNED_IN), probe(SIGNED_OUT, url="https://example.org/login.php")
        )

        assert trial.rules[0].on_live is True
        assert trial.rules[0].helps is False

    def test_says_nothing_about_a_rule_that_is_not_set(self) -> None:
        trial = verify(self.rules(success_pattern="Log out"), probe(SIGNED_IN), probe(SIGNED_OUT))

        assert [rule.rule for rule in trial.rules] == ["success_pattern"]

    def test_judges_a_failure_pattern_by_the_page_it_belongs_to(self) -> None:
        site = self.rules(failure_pattern="Remember me")
        trial = verify(site, probe(SIGNED_IN), probe(SIGNED_OUT))

        assert trial.rules[0].on_dead is True
        assert trial.rules[0].helps is True

    def test_reports_every_rule_even_when_the_first_decides(self) -> None:
        # The whole point: the verdict is settled by the login pattern, and the other two are
        # still accounted for.
        site = self.rules(
            login_url_pattern="login.php", success_pattern="Log out", failure_pattern="Remember me"
        )
        trial = verify(
            site, probe(SIGNED_IN), probe(SIGNED_OUT, url="https://example.org/login.php")
        )

        assert len(trial.rules) == 3
        assert all(rule.helps for rule in trial.rules)


class TestBothSpellingsOfTheVerb:
    """A page inviting you to "please login here" is missed by a list that knows only "log in"."""

    # The shape of a real logged-out landing page: it does not redirect, and its only invitation
    # to sign in spells the verb as one word.
    ONE_WORD = """
    <html><head><title>Somewhere</title></head><body>
    <b>Welcome Back!</b> Please login <a href="login.php">here!</a>
    <span>This is a mirage.</span>
    </body></html>
    """

    def test_finds_the_one_word_spelling(self) -> None:
        found = compare(probe(SIGNED_IN), probe(self.ONE_WORD))

        assert found.failure_pattern == "Please login"

    def test_does_not_match_the_bare_word_on_a_logged_in_page(self) -> None:
        # "login" alone is too loose to use: it is in the link and script names of pages that are
        # perfectly logged in, and a rule matching both pages tells them apart from nothing.
        logged_in = "<html><a href='login.php'>x</a> Log out</html>"

        found = compare(probe(logged_in), probe(self.ONE_WORD))

        assert found.failure_pattern == "Please login"
        assert found.success_pattern == "Log out"

    def test_a_welcome_back_on_the_logged_out_page_is_not_taken_as_a_signal(self) -> None:
        # This page greets a visitor with "Welcome Back!" while signed out. Anything read as
        # meaning "signed in" would be exactly backwards here.
        found = compare(probe(SIGNED_IN), probe(self.ONE_WORD))

        assert found.success_pattern == "Log out"
