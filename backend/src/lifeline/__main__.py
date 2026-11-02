"""Run the application with uvicorn, through jigkit: ``python -m lifeline [--reload]``.

A module rather than a script, so the container starts it as ``python -m lifeline`` and the
import path is the same as for every other entry point. jigkit's ``serve`` keeps the logging
configured here and believes X-Forwarded-For and X-Forwarded-Proto only from
``FORWARDED_ALLOW_IPS``: they decide the address the login throttle counts and whether the
session cookie is Secure.
"""

import sys

from jigkit.web import serve

from .config import get_settings
from .services import logs


def main(argv: list[str] | None = None) -> None:
    """Serve the application, reloading on source changes when asked to."""
    settings = get_settings()
    logs.configure(settings)
    reload = "--reload" in (argv if argv is not None else sys.argv[1:])
    # The login stream is a websocket; uvicorn[standard] supplies the implementation.
    serve("lifeline.api.app:create_app", settings, reload=reload, ws="auto")


if __name__ == "__main__":
    main()
