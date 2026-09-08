"""Fixtures for the HTTP tests."""

from collections.abc import Iterator

import pytest
import respx

# The catch-all is named so a test can take it out of the way. respx answers with the first
# route that matches, so a route added after this one would never be reached.
CATCH_ALL = "anything_else"


@pytest.fixture(autouse=True)
def no_outbound_requests() -> Iterator[respx.Router]:
    """Fail any test that reaches the network, and stub the one call that would.

    Saving a site fetches its icon, which is a real request to a real host. Left unmocked,
    the suite would depend on DNS and quietly send traffic to whatever host a fixture names.

    A test that wants a particular URL answered should call ``stub`` rather than adding a route
    directly, so its route is matched ahead of the catch-all.
    """
    with respx.mock(assert_all_called=False) as router:
        router.route(name=CATCH_ALL).respond(404)
        yield router


@pytest.fixture
def stub(no_outbound_requests: respx.Router) -> Iterator[respx.Router]:
    """The same router with the catch-all moved to the back, for tests that answer a URL.

    Everything not explicitly answered still gets a 404 rather than reaching the network.
    """
    router = no_outbound_requests
    router.pop(CATCH_ALL)
    yield router
    router.route(name=CATCH_ALL).respond(404)
