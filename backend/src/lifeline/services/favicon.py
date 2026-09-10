"""Fetching a site's icon, so the site list is scannable by eye.

Stored as a data URI on the site row rather than proxied on demand: it is a couple of
kilobytes, it changes almost never, and keeping it in the database means the UI makes no
request to the site being monitored just to draw a list.
"""

import base64
import logging
import re
import struct
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


# An .ico is an archive of the same picture at several sizes, and a site that offers every size
# up to 256x256 can easily run to a couple of hundred kilobytes — all but a few hundred bytes of
# which is of no use to a 16-pixel row. Taking one picture out is what makes such a site's icon
# usable at all, rather than raising the ceiling and carrying the rest of it in every listing.
_ICO_HEADER = struct.Struct("<HHH")
_ICO_ENTRY = struct.Struct("<BBBBHHII")
_ICO_ENTRY_SIZE = _ICO_ENTRY.size
# The size worth keeping: the list draws icons at 16 pixels, so this is the one that still looks
# right on a screen that draws two device pixels for each of them.
_WANTED_PIXELS = 32
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _as_data_uri(content: bytes, content_type: str) -> str | None:
    if not content:
        return None
    media_type = content_type.split(";")[0].strip() or "image/x-icon"
    if not media_type.startswith(_IMAGE_TYPES):
        return None
    if media_type == "application/octet-stream":
        media_type = "image/x-icon"

    if len(content) > MAX_ICON_BYTES:
        one = _one_frame(content)
        if one is None:
            return None
        content, media_type = one
        if len(content) > MAX_ICON_BYTES:
            return None
    return f"data:{media_type};base64,{base64.b64encode(content).decode()}"


def _one_frame(content: bytes) -> tuple[bytes, str] | None:
    """One picture out of a multi-size .ico, or None if this is not one.

    Returns a whole PNG where the chosen picture already is one, since modern .ico files embed
    them and a PNG on its own is both smaller and something every browser draws directly.
    """
    frames = _frames(content)
    if not frames:
        return None
    # Closest to the size actually drawn, and the smaller of two equally close ones.
    width, offset, size = min(
        frames, key=lambda frame: (abs(frame[0] - _WANTED_PIXELS), frame[2])
    )
    data = content[offset : offset + size]
    if len(data) != size:
        return None
    if data.startswith(_PNG_MAGIC):
        return data, "image/png"
    entry = _ICO_ENTRY.pack(
        width % 256, width % 256, 0, 0, 1, 32, len(data), _ICO_HEADER.size + _ICO_ENTRY_SIZE
    )
    return _ICO_HEADER.pack(0, 1, 1) + entry + data, "image/x-icon"


def _frames(content: bytes) -> list[tuple[int, int, int]]:
    """Every picture an .ico holds, as (width, offset, size)."""
    if len(content) < _ICO_HEADER.size:
        return []
    reserved, kind, count = _ICO_HEADER.unpack_from(content)
    if reserved != 0 or kind != 1 or not 0 < count < 256:
        return []
    frames = []
    for index in range(count):
        start = _ICO_HEADER.size + index * _ICO_ENTRY_SIZE
        if start + _ICO_ENTRY_SIZE > len(content):
            break
        width, _height, _colours, _pad, _planes, _bpp, size, offset = _ICO_ENTRY.unpack_from(
            content, start
        )
        # A zero width means 256 in this format, which is the largest and least wanted.
        frames.append((width or 256, offset, size))
    return frames


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
