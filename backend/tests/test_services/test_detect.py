"""Working out a site's rules by fetching it signed in and signed out."""

import httpx
import respx

from lifeline.services.detect import Detector, Probe, compare
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

