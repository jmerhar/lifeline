"""Fixtures for the HTTP tests."""

from collections.abc import Iterator

import pytest
import respx


@pytest.fixture(autouse=True)
def no_outbound_requests() -> Iterator[respx.Router]:
    """Fail any test that reaches the network, and stub the one call that would.

    Saving a site fetches its icon, which is a real request to a real host. Left unmocked,
    the suite would depend on DNS and quietly send traffic to whatever host a fixture names.
    """
    with respx.mock(assert_all_called=False) as router:
        router.route().respond(404)
        yield router
