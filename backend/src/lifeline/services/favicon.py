"""Fetching a site's icon, so the site list is scannable by eye.

Stored as a data URI on the site row rather than proxied on demand: it is a couple of
kilobytes, it changes almost never, and keeping it in the database means the UI makes no
request to the site being monitored just to draw a list.
"""

import base64
import logging
import re
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

# A generous ceiling for an icon. Anything larger is not an icon, and embedding it in every
# site listing would cost more than it is worth.
MAX_ICON_BYTES = 100_000

# The icon declarations worth honouring, in the order they are preferred.
_ICON_LINK = re.compile(
    r"""<link[^>]+rel=["']?[^"'>]*\bicon\b[^"'>]*["']?[^>]*>""", re.IGNORECASE
)
_HREF = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)

_IMAGE_TYPES = ("image/", "application/octet-stream")


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _as_data_uri(content: bytes, content_type: str) -> str | None:
    if not content or len(content) > MAX_ICON_BYTES:
        return None
    media_type = content_type.split(";")[0].strip() or "image/x-icon"
    if not media_type.startswith(_IMAGE_TYPES):
        return None
    if media_type == "application/octet-stream":
        media_type = "image/x-icon"
    return f"data:{media_type};base64,{base64.b64encode(content).decode()}"


async def fetch(url: str, *, client: httpx.AsyncClient) -> str | None:
    """The site's icon as a data URI, or None if it has none worth storing.

    Never raises: a missing icon is a cosmetic loss, and a site that is slow or hostile to
    an unauthenticated request must not be able to stop a site from being saved.
    """
    origin = _origin(url)
    if not origin.startswith(("http://", "https://")):
        return None

    try:
        response = await client.get(f"{origin}/favicon.ico")
        if response.status_code == 200:
            icon = _as_data_uri(response.content, response.headers.get("content-type", ""))
            if icon:
                return icon

        # Plenty of sites declare an icon somewhere else entirely and serve nothing at the
        # conventional path.
        page = await client.get(origin)
        if page.status_code != 200:
            return None
        for link in _ICON_LINK.findall(page.text[:200_000]):
            href = _HREF.search(link)
            if not href:
                continue
            candidate = await client.get(urljoin(origin, href.group(1)))
            if candidate.status_code != 200:
                continue
            icon = _as_data_uri(candidate.content, candidate.headers.get("content-type", ""))
            if icon:
                return icon
    except httpx.HTTPError as exc:
        logger.debug("could not fetch an icon for %s: %s", origin, exc)
    return None
