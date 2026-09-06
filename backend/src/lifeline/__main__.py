"""Run the application with uvicorn.

A module rather than a script, so the container starts it as ``python -m lifeline`` and the
import path is the same as for every other entry point.
"""

import sys

import uvicorn

from .config import get_settings

# Where uvicorn binds inside the container. The port is published to the host by the compose
# file, which is where a deployment decides what is reachable from outside.
HOST = "0.0.0.0"  # noqa: S104
PORT = 8000


def main(argv: list[str] | None = None) -> None:
    """Serve the application, reloading on source changes when asked to."""
    settings = get_settings()
    reload = "--reload" in (argv if argv is not None else sys.argv[1:])
    uvicorn.run(
        # Reloading requires an import string rather than a built application: the worker is
        # a fresh process, and it has to construct the app itself.
        "lifeline.api.app:create_app" if reload else create(),
        factory=reload,
        reload=reload,
        host=HOST,
        port=PORT,
        log_level=settings.log_level.lower(),
        # The login stream is a websocket; uvicorn[standard] supplies the implementation.
        ws="auto",
    )


def create() -> object:
    """Build the application for a non-reloading run."""
    from .api.app import create_app

    return create_app(get_settings())


if __name__ == "__main__":
    main()
