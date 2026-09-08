"""Reading, writing and merging the cookies that make up a session.

Sessions are stored in Playwright's ``storage_state`` shape — cookies plus per-origin
local storage — because that is what an interactive login produces and what replaying a
session through a browser consumes. An HTTP ping converts the same document to a cookie
jar and back, so both ping methods share one stored representation.
"""

import json
import re
from datetime import UTC, datetime
from http.cookiejar import Cookie
from typing import Any, TypedDict
from urllib.parse import urlsplit

import httpx

# Playwright's marker for a cookie that lasts only as long as the browser session.
SESSION_COOKIE_EXPIRY = -1.0

# What each source calls a cookie's expiry.
_EXPIRY_KEYS = ("expires", "expirationDate", "expiry", "expiration_date")

_SAME_SITE_VALUES = {
    "strict": "Strict",
    "lax": "Lax",
    "none": "None",
    "no_restriction": "None",
    "unspecified": "Lax",
}


class CookieDict(TypedDict, total=False):
    """One cookie, in Playwright's ``storage_state`` shape."""

    name: str
    value: str
    domain: str
    path: str
    expires: float
    httpOnly: bool
    secure: bool
    sameSite: str


class OriginDict(TypedDict):
    """One origin's local storage."""

    origin: str
    localStorage: list[dict[str, str]]


class StorageState(TypedDict):
    """A whole captured session."""

    cookies: list[CookieDict]
    origins: list[OriginDict]


class CookieParseError(ValueError):
    """The pasted text could not be read as cookies."""


def empty_state() -> StorageState:
    """A session with nothing in it."""
    return {"cookies": [], "origins": []}


def _normalise_same_site(raw: Any, secure: bool) -> str:
    """Map any source's SameSite spelling onto the three values Playwright accepts."""
    value = _SAME_SITE_VALUES.get(str(raw).strip().lower(), "Lax") if raw else "Lax"
    # A SameSite=None cookie is only valid when it is also Secure. Browsers reject the
    # combination outright, so an import that would produce it is downgraded rather than
    # stored as something that can never be sent.
    if value == "None" and not secure:
        return "Lax"
    return value


def _normalise_expiry(raw: dict[str, Any]) -> float:
    """Read whichever expiry key this source uses, in unix seconds."""
    if raw.get("session") is True:
        return SESSION_COOKIE_EXPIRY
    for key in _EXPIRY_KEYS:
        if key in raw and raw[key] is not None:
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                continue
            # Both 0 and -1 appear in the wild for "no expiry recorded".
            return value if value > 0 else SESSION_COOKIE_EXPIRY
    return SESSION_COOKIE_EXPIRY


def _normalise_cookie(raw: dict[str, Any], fallback_domain: str) -> CookieDict:
    """Coerce one cookie from any supported source into :class:`CookieDict`."""
    name = str(raw.get("name", "")).strip()
    if not name:
        raise CookieParseError("a cookie with no name cannot be stored")
    secure = bool(raw.get("secure", False))
    domain = str(raw.get("domain") or fallback_domain).strip()
    if not domain:
        raise CookieParseError(f"cookie {name!r} has no domain and none could be inferred")
    return {
        "name": name,
        "value": str(raw.get("value", "")),
        "domain": domain,
        "path": str(raw.get("path") or "/"),
        "expires": _normalise_expiry(raw),
        "httpOnly": bool(raw.get("httpOnly", raw.get("httponly", False))),
        "secure": secure,
        "sameSite": _normalise_same_site(raw.get("sameSite", raw.get("samesite")), secure),
    }


def normalise_state(raw: Any, fallback_domain: str = "") -> StorageState:
    """Validate and coerce a decoded document into a :class:`StorageState`."""
    if not isinstance(raw, dict):
        raise CookieParseError("expected an object with a 'cookies' key")
    cookies = raw.get("cookies")
    if not isinstance(cookies, list):
        raise CookieParseError("expected 'cookies' to be a list")
    origins: list[OriginDict] = []
    for origin in raw.get("origins") or []:
        if isinstance(origin, dict) and origin.get("origin"):
            origins.append(
                {
                    "origin": str(origin["origin"]),
                    "localStorage": [
                        {"name": str(item.get("name", "")), "value": str(item.get("value", ""))}
                        for item in origin.get("localStorage") or []
                        if isinstance(item, dict)
                    ],
                }
            )
    return {
        "cookies": [_normalise_cookie(cookie, fallback_domain) for cookie in cookies],
        "origins": origins,
    }


def default_domain_for(url: str) -> str:
    """The cookie domain to assume for an import that carries none.

    A pasted ``Cookie:`` header has no domain, and a host-only cookie on
    ``www.example.org`` would then not be sent to ``example.org`` (or the reverse) — which
    is how a hand-imported session appears to work and silently sends nothing. Dropping a
    leading ``www.`` and returning a dotted domain matches the whole site, which is what
    someone pasting their own cookies for that site means.
    """
    host = urlsplit(url).hostname or ""
    if not host:
        return ""
    host = host.removeprefix("www.")
    # A bare hostname with no dot (an intranet name) cannot take a leading dot: no
    # request would ever match it.
    return f".{host}" if "." in host else host


def parse_cookie_header(text: str, fallback_domain: str) -> StorageState:
    """Read a ``name=value; name=value`` header string."""
    state = empty_state()
    for part in text.replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        name, separator, value = part.partition("=")
        if not separator:
            raise CookieParseError(f"{part!r} is not a name=value pair")
        state["cookies"].append(
            _normalise_cookie({"name": name.strip(), "value": value.strip()}, fallback_domain)
        )
    if not state["cookies"]:
        raise CookieParseError("no cookies found")
    return state


def parse_cookie_json(text: str, fallback_domain: str) -> StorageState:
    """Read Playwright storage state, or a browser extension's cookie array."""
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieParseError(f"invalid JSON: {exc.msg}") from exc
    if isinstance(decoded, list):
        return normalise_state({"cookies": decoded}, fallback_domain)
    return normalise_state(decoded, fallback_domain)


def parse_netscape(text: str, fallback_domain: str) -> StorageState:
    """Read the ``cookies.txt`` format that curl, wget and several extensions write."""
    state = empty_state()
    for line in text.splitlines():
        stripped = line.strip()
        # `#HttpOnly_` is a real prefix in this format, not a comment.
        http_only = stripped.startswith("#HttpOnly_")
        if http_only:
            stripped = stripped.removeprefix("#HttpOnly_")
        elif not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split("\t")
        if len(fields) < 7:
            continue
        domain, include_subdomains, path, secure, expiry, name, value = fields[:7]
        # The second field says whether the cookie applies to subdomains; the leading dot
        # is how that is expressed in the storage-state shape.
        if include_subdomains.strip().upper() == "TRUE" and not domain.startswith("."):
            domain = f".{domain}"
        state["cookies"].append(
            _normalise_cookie(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": path,
                    "expires": expiry,
                    "secure": secure.strip().upper() == "TRUE",
                    "httpOnly": http_only,
                },
                fallback_domain,
            )
        )
    if not state["cookies"]:
        raise CookieParseError("no cookies found")
    return state


def parse_import(text: str, url: str) -> StorageState:
    """Read pasted cookies in whichever of the supported formats they are in.

    Detected rather than declared, because the person pasting has a clipboard, not a
    format name: an export from a cookie extension, a ``cookies.txt`` file, or the
    ``Cookie:`` header copied out of developer tools all arrive here.
    """
    stripped = text.strip()
    if not stripped:
        raise CookieParseError("nothing to import")
    fallback = default_domain_for(url)
    if stripped[0] in "{[":
        return parse_cookie_json(stripped, fallback)
    # The Netscape format is tab-separated with at least seven fields; a header string
    # never contains a tab.
    if any(len(line.split("\t")) >= 7 for line in stripped.splitlines()):
        return parse_netscape(stripped, fallback)
    return parse_cookie_header(stripped, fallback)


def _to_jar_cookie(cookie: CookieDict) -> Cookie:
    """Build the stdlib cookie that httpx's jar stores."""
    domain = cookie.get("domain", "")
    initial_dot = domain.startswith(".")
    expires = cookie.get("expires", SESSION_COOKIE_EXPIRY)
    has_expiry = expires is not None and expires > 0
    return Cookie(
        version=0,
        name=cookie["name"],
        value=cookie.get("value", ""),
        port=None,
        port_specified=False,
        domain=domain,
        domain_specified=initial_dot,
        domain_initial_dot=initial_dot,
        path=cookie.get("path", "/"),
        path_specified=True,
        secure=cookie.get("secure", False),
        expires=int(expires) if has_expiry else None,
        # A cookie with no expiry is a session cookie: kept for this run, and not treated
        # as something that has already lapsed.
        discard=not has_expiry,
        comment=None,
        comment_url=None,
        rest={"HttpOnly": ""} if cookie.get("httpOnly") else {},
        rfc2109=False,
    )


def state_to_jar(state: StorageState) -> httpx.Cookies:
    """Load a stored session into a jar a request can be made with.

    Handing the result to an httpx client copies the cookies into a *new* jar, so this
    object never sees what a response set: merge from ``client.cookies`` after the
    request, never from the jar passed in. Merging from the wrong one silently keeps the
    stale session and looks exactly like a site that does not rotate its cookies.
    """
    jar = httpx.Cookies()
    for cookie in state["cookies"]:
        jar.jar.set_cookie(_to_jar_cookie(cookie))
    return jar


def _from_jar_cookie(cookie: Cookie, previous: CookieDict | None) -> CookieDict:
    """Convert a jar cookie back to stored form, keeping what the jar cannot express."""
    return {
        "name": cookie.name,
        "value": cookie.value or "",
        "domain": cookie.domain,
        "path": cookie.path,
        "expires": float(cookie.expires) if cookie.expires else SESSION_COOKIE_EXPIRY,
        "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
        "secure": bool(cookie.secure),
        # The jar drops SameSite, so it is carried over from the stored cookie rather than
        # reset to a default that could stop the cookie being sent on a cross-site
        # navigation the site relies on.
        "sameSite": (previous or {}).get("sameSite", "Lax"),
    }


def _cookie_key(cookie: CookieDict) -> tuple[str, str, str]:
    """What makes a cookie the same cookie."""
    return cookie["name"], cookie.get("domain", ""), cookie.get("path", "/")


def merge_jar_into_state(state: StorageState, jar: httpx.Cookies) -> tuple[StorageState, bool]:
    """Fold the cookies a response set back into the stored session.

    This is not an optimisation. A session with a sliding expiry re-issues its cookie on
    every request, and some sites rotate the token itself, so discarding the response's
    cookies either throws away the extension the ping just earned or invalidates the
    session outright — turning the tool that exists to keep an account alive into the
    thing that logs it out.

    Returns the new state and whether anything actually changed, so a caller can record
    when a session last rotated.
    """
    previous = {_cookie_key(cookie): cookie for cookie in state["cookies"]}
    merged = [_from_jar_cookie(cookie, previous.get((cookie.name, cookie.domain, cookie.path)))
              for cookie in jar.jar]
    changed = len(merged) != len(previous) or any(
        _cookie_key(cookie) not in previous
        or previous[_cookie_key(cookie)].get("value") != cookie["value"]
        or previous[_cookie_key(cookie)].get("expires") != cookie["expires"]
        for cookie in merged
    )
    return {"cookies": merged, "origins": state["origins"]}, changed


def expires_at(state: StorageState) -> datetime | None:
    """When the last stored cookie stops being valid, if any of them say.

    The *last*, not the first. A login page leaves behind whatever its analytics and consent
    tooling set, and those expire in minutes — one of them being fifteen minutes old says nothing
    about whether the session still works. What can be said with confidence is that once every
    cookie has expired, nothing held here can possibly work any more, and that is the point worth
    knowing about.

    None when nothing carries an expiry, which is the usual case for a pure session cookie: it
    lasts until the site decides otherwise, and no date here can predict that.
    """
    expiries = [
        cookie["expires"]
        for cookie in state["cookies"]
        if cookie.get("expires") and cookie["expires"] > 0
    ]
    if not expiries:
        return None
    return datetime.fromtimestamp(max(expiries), tz=UTC)


def for_host(state: StorageState, host: str) -> StorageState:
    """Keep only the cookies that belong to ``host`` or a domain it sits under.

    A browser used for a login collects cookies from everything it touched, which is how a session
    captured for one site came to hold another site's login cookies entirely. They are never sent
    anywhere — a request only carries cookies matching its own host — so dropping them costs
    nothing, and keeping somebody's unrelated session encrypted in this database is not something
    to do by accident.
    """
    if not host:
        return state
    kept = [cookie for cookie in state["cookies"] if _belongs_to(cookie.get("domain", ""), host)]
    origins = [
        origin
        for origin in state["origins"]
        if _belongs_to(urlsplit(origin["origin"]).hostname or "", host)
    ]
    return {"cookies": kept, "origins": origins}


def _belongs_to(domain: str, host: str) -> bool:
    """Whether a cookie domain covers ``host``, or is a name under it."""
    domain = domain.lstrip(".").lower()
    host = host.lstrip(".").lower()
    if not domain:
        return False
    return domain == host or host.endswith(f".{domain}") or domain.endswith(f".{host}")


def foreign_domains(state: StorageState, host: str) -> list[str]:
    """The cookie domains in ``state`` that do not belong to ``host``, for logging."""
    return sorted(
        {
            cookie.get("domain", "")
            for cookie in state["cookies"]
            if not _belongs_to(cookie.get("domain", ""), host)
        }
    )


def cookie_names(state: StorageState) -> list[str]:
    """The names of the stored cookies, for display. Never their values."""
    return sorted({cookie["name"] for cookie in state["cookies"]})
