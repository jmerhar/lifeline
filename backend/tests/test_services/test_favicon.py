"""Fetching a site's icon."""

import base64

import httpx
import pytest
import respx

from lifeline.services import favicon

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
async def client() -> httpx.AsyncClient:
    async with httpx.AsyncClient(follow_redirects=True) as instance:
        yield instance


class TestFetch:
    @respx.mock
    async def test_prefers_the_conventional_path(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )

        icon = await favicon.fetch("https://example.org/home", client=client)

        assert icon.startswith("data:image/png;base64,")

    @respx.mock
    async def test_falls_back_to_the_declared_icon(self, client: httpx.AsyncClient) -> None:
        # Plenty of sites serve nothing at /favicon.ico and declare the icon in the page.
        # Registered before the origin route: respx matches in order, and a route given only
        # an origin also matches paths under it.
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org/img/logo.png").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(
            200, html='<html><head><link rel="shortcut icon" href="/img/logo.png"></head></html>'
        )

        icon = await favicon.fetch("https://example.org/home", client=client)

        assert icon.startswith("data:image/png;base64,")

    @respx.mock
    async def test_treats_an_octet_stream_as_an_icon(self, client: httpx.AsyncClient) -> None:
        # Which is what a good many servers send for a .ico file.
        respx.get("https://example.org/favicon.ico").respond(
            200, content=PNG, headers={"content-type": "application/octet-stream"}
        )

        assert (await favicon.fetch("https://example.org/", client=client)).startswith(
            "data:image/x-icon;base64,"
        )

    @respx.mock
    async def test_refuses_something_that_is_not_an_image(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, text="<html>not found</html>", headers={"content-type": "text/html"}
        )
        respx.get("https://example.org").respond(200, html="<html><head></head></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_refuses_an_icon_that_is_too_large(self, client: httpx.AsyncClient) -> None:
        # Embedded in every site listing, so the size ceiling is the point.
        respx.get("https://example.org/favicon.ico").respond(
            200,
            content=b"x" * (favicon.MAX_ICON_BYTES + 1),
            headers={"content-type": "image/png"},
        )
        respx.get("https://example.org").respond(200, html="<html></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_refuses_an_empty_response(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(
            200, content=b"", headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(200, html="<html></html>")

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_gives_up_quietly_when_the_site_is_unreachable(
        self, client: httpx.AsyncClient
    ) -> None:
        # A missing icon is cosmetic; a slow or hostile site must not stop a site being saved.
        respx.get("https://example.org/favicon.ico").mock(
            side_effect=httpx.ConnectError("no route")
        )

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_gives_up_when_the_home_page_is_not_available(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org").respond(500)

        assert await favicon.fetch("https://example.org/", client=client) is None

    @respx.mock
    async def test_skips_a_declared_icon_that_cannot_be_fetched(
        self, client: httpx.AsyncClient
    ) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org/gone.png").respond(404)
        respx.get("https://example.org/ok.png").respond(
            200, content=PNG, headers={"content-type": "image/png"}
        )
        respx.get("https://example.org").respond(
            200, html='<link rel="icon" href="/gone.png"><link rel="icon" href="/ok.png">'
        )

        assert await favicon.fetch("https://example.org/", client=client) is not None

    @respx.mock
    async def test_ignores_a_link_tag_with_no_href(self, client: httpx.AsyncClient) -> None:
        respx.get("https://example.org/favicon.ico").respond(404)
        respx.get("https://example.org").respond(200, html='<link rel="icon" sizes="16x16">')

        assert await favicon.fetch("https://example.org/", client=client) is None

    async def test_refuses_a_url_that_is_not_http(self, client: httpx.AsyncClient) -> None:
        assert await favicon.fetch("file:///etc/passwd", client=client) is None


def build_ico(*frames: tuple[int, bytes]) -> bytes:
    """A valid .ico holding the given (width, data) pictures."""
    import struct

    header = struct.pack("<HHH", 0, 1, len(frames))
    directory = b""
    offset = len(header) + 16 * len(frames)
    for width, data in frames:
        directory += struct.pack(
            "<BBBBHHII", width % 256, width % 256, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    return header + directory + b"".join(data for _, data in frames)


class TestAnIconTooLargeToStoreWhole:
    """An .ico is the same picture at several sizes, and all but one of them is waste."""

    def big(self, size: int) -> bytes:
        return b"\x00" * size

    def test_keeps_one_picture_out_of_an_oversized_icon(self) -> None:
        # A real site's icon: every size up to 256, adding to more than the ceiling, of which the
        # 32-pixel one is a few hundred bytes.
        ico = build_ico(
            (16, self.big(500)),
            (32, self.big(800)),
            (256, self.big(favicon.MAX_ICON_BYTES)),
        )
        assert len(ico) > favicon.MAX_ICON_BYTES

        uri = favicon._as_data_uri(ico, "image/x-icon")

        assert uri is not None
        assert uri.startswith("data:image/x-icon;base64,")
        assert len(base64.b64decode(uri.split(",", maxsplit=1)[1])) < 1000

    def test_prefers_the_size_the_list_actually_draws(self) -> None:
        ico = build_ico((16, b"a" * 400), (32, b"b" * 400), (128, self.big(favicon.MAX_ICON_BYTES)))

        uri = favicon._as_data_uri(ico, "image/x-icon")

        assert b"b" * 400 in base64.b64decode(uri.split(",", maxsplit=1)[1])

    def test_hands_back_an_embedded_png_as_a_png(self) -> None:
        # Modern .ico files embed them, and a PNG on its own is smaller and drawn directly.
        png = b"\x89PNG\r\n\x1a\n" + b"pretend this is a png"
        ico = build_ico((32, png), (256, self.big(favicon.MAX_ICON_BYTES)))

        uri = favicon._as_data_uri(ico, "image/x-icon")

        assert uri == f"data:image/png;base64,{base64.b64encode(png).decode()}"

    def test_leaves_an_icon_that_already_fits_alone(self) -> None:
        small = build_ico((32, b"x" * 100))

        uri = favicon._as_data_uri(small, "image/x-icon")

        assert base64.b64decode(uri.split(",", maxsplit=1)[1]) == small

    def test_refuses_something_too_large_that_is_not_an_icon(self) -> None:
        too_big = b"\x89PNG\r\n\x1a\n" + b"\x00" * favicon.MAX_ICON_BYTES

        assert favicon._as_data_uri(too_big, "image/png") is None

    def test_refuses_an_icon_whose_directory_lies(self) -> None:
        # An entry pointing past the end of the file; nothing here should read beyond it.
        import struct

        broken = (
            struct.pack("<HHH", 0, 1, 1)
            + struct.pack(
                "<BBBBHHII", 32, 32, 0, 0, 1, 32, favicon.MAX_ICON_BYTES, 9_000_000
            )
            + b"\x00" * (favicon.MAX_ICON_BYTES + 1)
        )

        assert favicon._as_data_uri(broken, "image/x-icon") is None


# The shape of a real site's icon that this could not store: six sizes adding to more than the
# ceiling, the largest of them an embedded PNG. Only the directory is real — each picture is
# filler of the right length, since the artwork is neither ours nor needed to test the arithmetic.
REAL_WORLD_FRAMES = ((256, 57802, True), (128, 67624, False), (64, 16936, False),
                     (48, 9640, False), (32, 4264, False), (16, 1128, False))


def build_real_world_ico() -> bytes:
    import struct

    header = struct.pack("<HHH", 0, 1, len(REAL_WORLD_FRAMES))
    directory = b""
    offset = len(header) + 16 * len(REAL_WORLD_FRAMES)
    blobs = []
    for width, size, is_png in REAL_WORLD_FRAMES:
        data = (b"\x89PNG\r\n\x1a\n" + bytes(size - 8)) if is_png else bytes(size)
        blobs.append(data)
        directory += struct.pack("<BBBBHHII", width % 256, width % 256, 0, 0, 1, 32, size, offset)
        offset += size
    return header + directory + b"".join(blobs)


class TestTheIconThatStartedThis:
    """The shape that made a real site show no icon at all."""

    def test_stores_it_now(self) -> None:
        ico = build_real_world_ico()
        assert len(ico) > favicon.MAX_ICON_BYTES

        uri = favicon._as_data_uri(ico, "image/x-icon")

        assert uri is not None

    def test_stores_a_fortieth_of_it(self) -> None:
        # The 32-pixel picture, which is all a list drawing 16-pixel rows can use.
        uri = favicon._as_data_uri(build_real_world_ico(), "image/x-icon")

        stored = base64.b64decode(uri.split(",", maxsplit=1)[1])
        assert len(stored) < 5_000

    def test_does_not_take_the_largest_picture_just_because_it_is_a_png(self) -> None:
        # The 256-pixel one is an embedded PNG and would be handed back whole; it is 57 kB.
        uri = favicon._as_data_uri(build_real_world_ico(), "image/x-icon")

        assert uri.startswith("data:image/x-icon;base64,")
