"""Parsing, replaying and merging session cookies."""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from lifeline.services.cookies import (
    SESSION_COOKIE_EXPIRY,
    CookieParseError,
    cookie_names,
    default_domain_for,
    empty_state,
    expires_at,
    for_host,
    foreign_domains,
    merge_jar_into_state,
    normalise_state,
    parse_import,
    state_to_jar,
    storage_names,
)

FUTURE = 4102444800.0  # 2100-01-01, comfortably beyond any test run.


def state_with(**overrides: object) -> dict:
    """A one-cookie state, for the merge tests."""
    cookie = {
        "name": "session",
        "value": "original",
        "domain": ".example.org",
        "path": "/",
        "expires": FUTURE,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }
    cookie.update(overrides)
    return {"cookies": [cookie], "origins": []}


class TestDefaultDomain:
    def test_drops_www_and_returns_a_dotted_domain(self) -> None:
        # Dotted so a session imported for www.example.org is still sent to example.org.
        assert default_domain_for("https://www.example.org/index.php") == ".example.org"

    def test_keeps_a_host_that_is_already_bare(self) -> None:
        assert default_domain_for("https://tracker.example.org/") == ".tracker.example.org"

    def test_leaves_a_dotless_host_undotted(self) -> None:
        # ".intranet" would match no request at all.
        assert default_domain_for("http://intranet/") == "intranet"

    def test_handles_a_url_with_no_host(self) -> None:
        assert default_domain_for("not-a-url") == ""


class TestParseHeader:
    def test_reads_a_pasted_cookie_header(self) -> None:
        state = parse_import("uid=1234; pass=abcdef; __cf_bm=xyz", "https://example.org/")

        assert cookie_names(state) == ["__cf_bm", "pass", "uid"]
        assert [cookie["domain"] for cookie in state["cookies"]] == [".example.org"] * 3
        assert state["cookies"][0]["value"] == "1234"

    def test_keeps_a_value_containing_an_equals_sign(self) -> None:
        state = parse_import("token=abc=def==", "https://example.org/")

        assert state["cookies"][0]["value"] == "abc=def=="

    def test_treats_a_header_cookie_as_a_session_cookie(self) -> None:
        # A header carries no expiry; recording one would be an invention.
        state = parse_import("uid=1", "https://example.org/")

        assert state["cookies"][0]["expires"] == SESSION_COOKIE_EXPIRY

    def test_rejects_text_that_is_not_name_value_pairs(self) -> None:
        with pytest.raises(CookieParseError, match="not a name=value pair"):
            parse_import("this is just prose", "https://example.org/")

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(CookieParseError, match="nothing to import"):
            parse_import("   \n  ", "https://example.org/")


class TestParseJson:
    def test_reads_playwright_storage_state(self) -> None:
        state = parse_import(
            """
            {"cookies": [{"name": "session", "value": "v", "domain": ".example.org",
                          "path": "/", "expires": 4102444800, "httpOnly": true,
                          "secure": true, "sameSite": "Lax"}],
             "origins": [{"origin": "https://example.org",
                          "localStorage": [{"name": "theme", "value": "dark"}]}]}
            """,
            "https://example.org/",
        )

        assert state["cookies"][0]["expires"] == 4102444800
        assert state["origins"][0]["localStorage"] == [{"name": "theme", "value": "dark"}]

    def test_reads_a_browser_extension_cookie_array(self) -> None:
        # Cookie-Editor and friends export a bare array with expirationDate.
        state = parse_import(
            """
            [{"name": "uid", "value": "1", "domain": ".example.org", "path": "/",
              "expirationDate": 4102444800, "secure": true, "sameSite": "no_restriction"},
             {"name": "tmp", "value": "2", "domain": ".example.org", "session": true}]
            """,
            "https://example.org/",
        )

        assert state["cookies"][0]["expires"] == 4102444800
        assert state["cookies"][0]["sameSite"] == "None"
        assert state["cookies"][1]["expires"] == SESSION_COOKIE_EXPIRY

    def test_downgrades_samesite_none_without_secure(self) -> None:
        # Browsers refuse SameSite=None on a non-Secure cookie, so storing it would
        # produce a cookie that can never be sent.
        state = parse_import(
            '[{"name": "a", "value": "b", "domain": "x.example.org", "sameSite": "none"}]',
            "https://example.org/",
        )

        assert state["cookies"][0]["sameSite"] == "Lax"

    def test_falls_back_to_the_site_domain_when_an_export_omits_it(self) -> None:
        state = parse_import('[{"name": "a", "value": "b"}]', "https://www.example.org/")

        assert state["cookies"][0]["domain"] == ".example.org"

    def test_treats_a_zero_expiry_as_a_session_cookie(self) -> None:
        state = parse_import(
            '[{"name": "a", "value": "b", "domain": "x.org", "expirationDate": 0}]',
            "https://x.org/",
        )

        assert state["cookies"][0]["expires"] == SESSION_COOKIE_EXPIRY

    def test_ignores_an_unparseable_expiry(self) -> None:
        state = parse_import(
            '[{"name": "a", "value": "b", "domain": "x.org", "expirationDate": "soon"}]',
            "https://x.org/",
        )

        assert state["cookies"][0]["expires"] == SESSION_COOKIE_EXPIRY

    def test_rejects_invalid_json(self) -> None:
        with pytest.raises(CookieParseError, match="invalid JSON"):
            parse_import("{not json", "https://example.org/")

    def test_rejects_json_without_cookies(self) -> None:
        with pytest.raises(CookieParseError, match="'cookies' to be a list"):
            parse_import('{"origins": []}', "https://example.org/")

    def test_rejects_a_cookie_with_no_name(self) -> None:
        with pytest.raises(CookieParseError, match="no name"):
            parse_import('[{"value": "orphan", "domain": "x.org"}]', "https://x.org/")

    def test_rejects_a_cookie_with_no_inferable_domain(self) -> None:
        with pytest.raises(CookieParseError, match="no domain"):
            parse_import('[{"name": "a", "value": "b"}]', "not-a-url")


class TestParseNetscape:
    def test_reads_a_cookies_txt_file(self) -> None:
        state = parse_import(
            "# Netscape HTTP Cookie File\n"
            ".example.org\tTRUE\t/\tTRUE\t4102444800\tsession\tabc123\n"
            "#HttpOnly_.example.org\tTRUE\t/\tTRUE\t4102444800\tpass\tdef456\n",
            "https://example.org/",
        )

        assert cookie_names(state) == ["pass", "session"]
        assert state["cookies"][0]["secure"] is True
        # `#HttpOnly_` is a real prefix in this format, not a comment.
        assert state["cookies"][1]["httpOnly"] is True

    def test_adds_the_leading_dot_when_the_file_says_subdomains(self) -> None:
        state = parse_import(
            "example.org\tTRUE\t/\tFALSE\t4102444800\ta\tb\n", "https://example.org/"
        )

        assert state["cookies"][0]["domain"] == ".example.org"

    def test_keeps_a_host_only_cookie_host_only(self) -> None:
        state = parse_import(
            "example.org\tFALSE\t/\tFALSE\t4102444800\ta\tb\n", "https://example.org/"
        )

        assert state["cookies"][0]["domain"] == "example.org"

    def test_skips_short_lines(self) -> None:
        state = parse_import(
            "truncated\tTRUE\t/\n.example.org\tTRUE\t/\tTRUE\t4102444800\ta\tb\n",
            "https://example.org/",
        )

        assert cookie_names(state) == ["a"]

    def test_rejects_a_file_with_no_usable_lines(self) -> None:
        with pytest.raises(CookieParseError, match="no cookies found"):
            parse_import("a\tb\tc\td\te\tf\tg\nx\ty\tz\n".replace("a\tb", "#a\tb"), "https://x.org/")


class TestReplay:
    @respx.mock
    async def test_a_stored_session_is_sent_on_the_request(self) -> None:
        route = respx.get("https://example.org/home").respond(200, text="ok")

        async with httpx.AsyncClient(cookies=state_to_jar(state_with())) as client:
            await client.get("https://example.org/home")

        assert route.calls.last.request.headers["cookie"] == "session=original"

    @respx.mock
    async def test_a_secure_cookie_is_withheld_from_a_plain_http_request(self) -> None:
        route = respx.get("http://example.org/home").respond(200)

        async with httpx.AsyncClient(cookies=state_to_jar(state_with())) as client:
            await client.get("http://example.org/home")

        assert "cookie" not in route.calls.last.request.headers

    @respx.mock
    async def test_a_dotted_cookie_reaches_a_subdomain(self) -> None:
        route = respx.get("https://www.example.org/home").respond(200)

        async with httpx.AsyncClient(cookies=state_to_jar(state_with())) as client:
            await client.get("https://www.example.org/home")

        assert route.calls.last.request.headers["cookie"] == "session=original"

    @respx.mock
    async def test_a_host_only_cookie_does_not_reach_a_sibling_host(self) -> None:
        route = respx.get("https://other.example.org/home").respond(200)
        jar = state_to_jar(state_with(domain="www.example.org"))

        async with httpx.AsyncClient(cookies=jar) as client:
            await client.get("https://other.example.org/home")

        assert "cookie" not in route.calls.last.request.headers

    def test_a_session_cookie_is_not_treated_as_expired(self) -> None:
        jar = state_to_jar(state_with(expires=SESSION_COOKIE_EXPIRY))

        assert [cookie.name for cookie in jar.jar] == ["session"]


class TestMerge:
    @respx.mock
    async def test_a_reissued_cookie_replaces_the_stored_one(self) -> None:
        # The behaviour the whole tool depends on: a sliding-expiry session hands back a
        # fresh cookie, and keeping the old one throws away the extension just earned.
        respx.get("https://example.org/home").respond(
            200, headers={"set-cookie": "session=rotated; Domain=.example.org; Path=/; Secure"}
        )
        async with httpx.AsyncClient(cookies=state_to_jar(state_with())) as client:
            await client.get("https://example.org/home")
            # Read back from the client, not from the jar handed to it: httpx copies a
            # Cookies instance, so the original object is never updated.
            merged, changed = merge_jar_into_state(state_with(), client.cookies)

        assert changed is True
        assert merged["cookies"][0]["value"] == "rotated"

    @respx.mock
    async def test_a_newly_set_cookie_is_added(self) -> None:
        respx.get("https://example.org/home").respond(
            200, headers={"set-cookie": "csrf=zzz; Domain=.example.org; Path=/"}
        )
        async with httpx.AsyncClient(cookies=state_to_jar(state_with())) as client:
            await client.get("https://example.org/home")
            merged, changed = merge_jar_into_state(state_with(), client.cookies)

        assert changed is True
        assert cookie_names(merged) == ["csrf", "session"]

    def test_an_unchanged_jar_reports_no_rotation(self) -> None:
        state = state_with()

        merged, changed = merge_jar_into_state(state, state_to_jar(state))

        assert changed is False
        assert merged["cookies"][0]["value"] == "original"

    def test_a_changed_expiry_alone_counts_as_rotation(self) -> None:
        state = state_with()
        jar = state_to_jar(state_with(expires=FUTURE - 100))

        _, changed = merge_jar_into_state(state, jar)

        assert changed is True

    def test_local_storage_survives_a_merge(self) -> None:
        # The jar knows nothing about local storage, so a naive rebuild would drop the
        # half of the session that a browser-mode ping needs.
        state = state_with()
        state["origins"] = [
            {"origin": "https://example.org", "localStorage": [{"name": "k", "value": "v"}]}
        ]

        merged, _ = merge_jar_into_state(state, state_to_jar(state))

        assert merged["origins"] == state["origins"]

    def test_samesite_survives_a_merge(self) -> None:
        # Cookie jars drop SameSite entirely; re-deriving it would silently change how the
        # cookie behaves on the site's own cross-site navigations.
        state = state_with(sameSite="Strict")

        merged, _ = merge_jar_into_state(state, state_to_jar(state))

        assert merged["cookies"][0]["sameSite"] == "Strict"

    def test_http_only_survives_a_merge(self) -> None:
        state = state_with(httpOnly=True)

        merged, _ = merge_jar_into_state(state, state_to_jar(state))

        assert merged["cookies"][0]["httpOnly"] is True


class TestEdgeCases:
    def test_rejects_a_document_that_is_not_a_storage_state(self) -> None:
        # normalise_state also takes what a browser hands back, which is not always what the
        # caller believes it is.
        with pytest.raises(CookieParseError, match="an object with a 'cookies' key"):
            normalise_state(["not", "a", "storage", "state"])

    def test_rejects_prose_that_is_not_cookies_at_all(self) -> None:
        with pytest.raises(CookieParseError, match="not a name=value pair"):
            parse_import('"just a string"', "https://example.org/")

    def test_skips_a_blank_line_in_a_cookie_header(self) -> None:
        state = parse_import("uid=1;\n\n;pass=2", "https://example.org/")

        assert cookie_names(state) == ["pass", "uid"]

    def test_rejects_a_header_of_only_separators(self) -> None:
        with pytest.raises(CookieParseError, match="no cookies found"):
            parse_import(";;;", "https://example.org/")


class TestScopingToTheSite:
    """A browser used for a login collects cookies from everything it touched."""

    def build(self) -> dict:
        return {
            "cookies": [
                {"name": "session", "value": "s", "domain": "example.org", "path": "/",
                 "expires": FUTURE},
                {"name": "_dd_s", "value": "a", "domain": ".example.org", "path": "/",
                 "expires": 1757347245.0},
                {"name": "_gh_sess", "value": "g", "domain": "github.com", "path": "/",
                 "expires": FUTURE},
            ],
            "origins": [
                {"origin": "https://example.org", "localStorage": [{"name": "k", "value": "v"}]},
                {"origin": "https://github.com", "localStorage": [{"name": "gh", "value": "x"}]},
            ],
        }

    def test_keeps_the_sites_own_cookies(self) -> None:
        kept = for_host(self.build(), "example.org")

        assert cookie_names(kept) == ["_dd_s", "session"]

    def test_drops_another_sites_cookies(self) -> None:
        # This is not hypothetical: a captured session held somebody's GitHub login cookies, which a
        # ping would never send and which have no business being kept.
        assert "_gh_sess" not in cookie_names(for_host(self.build(), "example.org"))

    def test_drops_another_sites_local_storage(self) -> None:
        kept = for_host(self.build(), "example.org")

        assert [origin["origin"] for origin in kept["origins"]] == ["https://example.org"]

    def test_names_what_it_would_drop(self) -> None:
        assert foreign_domains(self.build(), "example.org") == ["github.com"]

    def test_keeps_a_parent_domain_cookie(self) -> None:
        # A cookie on .example.org belongs to www.example.org.
        state = {"cookies": [{"name": "s", "value": "v", "domain": ".example.org", "path": "/"}],
                 "origins": []}

        assert cookie_names(for_host(state, "www.example.org")) == ["s"]

    def test_keeps_a_subdomain_cookie(self) -> None:
        # A login that set something on auth.example.org while the site is example.org.
        state = {
            "cookies": [
                {"name": "s", "value": "v", "domain": "auth.example.org", "path": "/"}
            ],
                 "origins": []}

        assert cookie_names(for_host(state, "example.org")) == ["s"]

    def test_keeps_everything_when_the_host_is_unknown(self) -> None:
        # Better to store more than to throw away the session over a URL that would not parse.
        assert len(for_host(self.build(), "")["cookies"]) == 3


class TestExpiresAt:
    def test_reports_the_last_expiry_not_the_first(self) -> None:
        # The first is a fifteen-minute analytics cookie; it says nothing about the session. The
        # last
        # is the point after which nothing stored here can work.
        state = empty_state()
        state["cookies"] = [
            {"name": "_dd_s", "value": "a", "domain": "x.org", "path": "/",
             "expires": 1757347245.0},
            {"name": "session", "value": "s", "domain": "x.org", "path": "/", "expires": FUTURE},
        ]

        assert expires_at(state) == datetime.fromtimestamp(FUTURE, tz=UTC)

    def test_reports_nothing_when_no_cookie_carries_an_expiry(self) -> None:
        assert expires_at(state_with(expires=SESSION_COOKIE_EXPIRY)) is None


class TestASiteThatKeepsItsSessionOutsideCookies:
    """A single-page application usually holds its token in local storage, not in a cookie."""

    def state(self) -> dict:
        return {
            "cookies": [
                {"name": "_gh_sess", "value": "g", "domain": "github.com", "path": "/"},
                {"name": "logged_in", "value": "y", "domain": ".github.com", "path": "/"},
            ],
            "origins": [
                {
                    "origin": "https://app.example",
                    "localStorage": [{"name": "auth.token", "value": "t"}],
                },
                {"origin": "https://github.com", "localStorage": [{"name": "gh", "value": "x"}]},
            ],
        }

    def test_drops_foreign_cookies_even_when_the_site_has_none_of_its_own(self) -> None:
        # Measuring only cookies read this as "scoping would throw the session away" and kept
        # every foreign cookie — on every write, so for ever.
        kept = for_host(self.state(), "app.example")

        assert cookie_names(kept) == []
        assert [origin["origin"] for origin in kept["origins"]] == ["https://app.example"]

    def test_still_refuses_to_leave_nothing_at_all(self) -> None:
        # The guard is about losing a session, and with neither a cookie nor an origin of its own
        # there is nothing here that belongs to this site.
        state = {
            "cookies": [{"name": "s", "value": "v", "domain": "elsewhere.example", "path": "/"}],
            "origins": [],
        }

        assert for_host(state, "app.example") == state

    def test_names_the_foreign_domains_it_dropped(self) -> None:
        assert foreign_domains(self.state(), "app.example") == [".github.com", "github.com"]


class TestNamingWhatIsStored:
    def test_reports_the_keys_held_per_origin(self) -> None:
        state = {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://app.example",
                    "localStorage": [
                        {"name": "auth.token", "value": "secret"},
                        {"name": "auth.settings", "value": "{}"},
                    ],
                }
            ],
        }

        assert storage_names(state) == ["auth.settings", "auth.token"]

    def test_never_reports_a_value(self) -> None:
        # The same rule as cookies: a name says what is held, a value *is* the session.
        state = {
            "cookies": [],
            "origins": [
                {
                    "origin": "https://app.example",
                    "localStorage": [{"name": "k", "value": "SECRET"}],
                }
            ],
        }

        assert "SECRET" not in str(storage_names(state))

    def test_reports_nothing_for_a_session_of_cookies_alone(self) -> None:
        assert storage_names(state_with(name="session")) == []
