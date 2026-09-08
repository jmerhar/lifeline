"""SPIKE: serving a site's login pages through lifeline, to your own browser.

The idea under test: lifeline sits in the middle of the login instead of running a browser of its
own. It fetches the site's pages, rewrites their links so they come back through lifeline, and keeps
the cookies the site hands out. Your own browser renders it, so your own password manager fills it,
and the image needs no Chromium.

Deliberately minimal. It rewrites what HTML and CSS *declare* and nothing that JavaScript computes,
because the question is whether a real login survives that — not how much rewriting could eventually
be made to work. See docs/proxy-login-spike.md.
"""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

# Headers describing one hop rather than the content, which must not be passed along. Content
# encoding and length go too: httpx has already decoded the body, so both would be wrong.
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "content-encoding",
        "content-length",
    }
)

# Dropped from the response. These exist to stop a page being framed, or its resources loaded from
# anywhere but the site's own origin — exactly what proxying does. Worth naming plainly: the spike
# only works by disabling protections the site asked the browser to enforce.
STRIPPED = frozenset({"content-security-policy", "content-security-policy-report-only",
                      "x-frame-options", "strict-transport-security"})

# Attributes whose value is a URL that has to be redirected back through lifeline.
_URL_ATTRIBUTE = re.compile(
    r"""(?P<attr>\b(?:href|src|action|poster|formaction)\s*=\s*)(?P<quote>["'])(?P<url>[^"']*)\2""",
    re.IGNORECASE,
)
_CSS_URL = re.compile(r"""url\(\s*(?P<quote>["']?)(?P<url>[^"')]+)(?P=quote)\s*\)""", re.IGNORECASE)


@dataclass
class ProxiedResponse:
    """What the browser should be sent back."""

    status_code: int
    headers: dict[str, str]
    body: bytes


def rewrite_url(url: str, *, base: str, origin: str, prefix: str) -> str:
    """Point one URL back through lifeline, if it belongs to the site being proxied.

    Anything pointing elsewhere is left alone: a login page that loads a font from a CDN should
    still load it from there, and routing it through lifeline would gain nothing but latency.
    """
    stripped = url.strip()
    if not stripped or stripped.startswith(("#", "data:", "mailto:", "javascript:", "about:")):
        return url
    absolute = urljoin(base, stripped)
    if not absolute.startswith(origin):
        return url
    path = absolute[len(origin) :] or "/"
    return f"{prefix}{path}"


def rewrite_html(body: str, *, base: str, origin: str, prefix: str) -> str:
    """Redirect the URLs an HTML document declares.

    Only what is written in the markup. A URL that JavaScript builds at runtime — `fetch('/api/x')`
    — is untouched and will resolve against lifeline's own root, which is the first thing expected to
    break on a site that logs in over XHR.
    """

    def attribute(match: re.Match[str]) -> str:
        new = rewrite_url(match.group("url"), base=base, origin=origin, prefix=prefix)
        return f"{match.group('attr')}{match.group('quote')}{new}{match.group('quote')}"

    return _CSS_URL.sub(
        lambda m: _css_replacement(m, base=base, origin=origin, prefix=prefix),
        _URL_ATTRIBUTE.sub(attribute, body),
    )


def _css_replacement(match: re.Match[str], *, base: str, origin: str, prefix: str) -> str:
    new = rewrite_url(match.group("url"), base=base, origin=origin, prefix=prefix)
    quote = match.group("quote")
    return f"url({quote}{new}{quote})"


class LoginProxy:
    """Fetches a site's pages on the browser's behalf, keeping the cookies for itself.

    The jar stays here rather than being handed to the browser. That is the whole point: the browser
    gets a usable login page, and lifeline ends up holding the session — which is what it needs.
    """

    def __init__(self, user_agent: str, timeout: float = 30.0) -> None:
        self._user_agent = user_agent
        self._timeout = timeout
        self.cookies = httpx.Cookies()

    async def forward(
        self,
        *,
        origin: str,
        path: str,
        prefix: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> ProxiedResponse:
        """Make one request to the site and prepare the answer for the browser."""
        target = f"{origin}{path}"
        sent = {
            # The site is told the browser's own accept headers and content type, but the agent is
            # lifeline's: it is the machine making the request, and a challenge that pins a session
            # to an agent should pin it to this one.
            "User-Agent": self._user_agent,
            **{
                name: value
                for name, value in (headers or {}).items()
                if name.lower() in ("accept", "accept-language", "content-type", "referer")
            },
        }

        async with httpx.AsyncClient(
            cookies=self.cookies, timeout=self._timeout, follow_redirects=False
        ) as client:
            response = await client.request(method, target, content=body, headers=sent)
            self.cookies = client.cookies

        return ProxiedResponse(
            status_code=response.status_code,
            headers=self._response_headers(response, origin=origin, prefix=prefix),
            body=self._response_body(response, base=target, origin=origin, prefix=prefix),
        )

    def _response_headers(
        self, response: httpx.Response, *, origin: str, prefix: str
    ) -> dict[str, str]:
        headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in HOP_BY_HOP and name.lower() not in STRIPPED
        }
        # The site's own cookies stay here. Passing them to the browser would put a session for
        # another domain on lifeline's, which is both useless to the browser and a way to leak it.
        headers.pop("set-cookie", None)
        location = response.headers.get("location")
        if location:
            headers["location"] = rewrite_url(location, base=origin, origin=origin, prefix=prefix)
        return headers

    def _response_body(
        self, response: httpx.Response, *, base: str, origin: str, prefix: str
    ) -> bytes:
        content_type = response.headers.get("content-type", "")
        if "html" in content_type:
            return rewrite_html(
                response.text, base=base, origin=origin, prefix=prefix
            ).encode(response.encoding or "utf-8")
        if "css" in content_type:
            rewritten = _CSS_URL.sub(
                lambda m: _css_replacement(m, base=base, origin=origin, prefix=prefix),
                response.text,
            )
            return rewritten.encode(response.encoding or "utf-8")
        # Everything else — images, fonts, and scripts — is passed through untouched. Scripts are
        # where this approach is expected to fail, and rewriting them by regular expression would
        # trade a visible failure for an unpredictable one.
        return response.content


def origin_of(url: str) -> str:
    """The scheme and host of a URL, with no path."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
