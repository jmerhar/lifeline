"""Setting and clearing the browser's login cookie, through jigkit.

The Secure flag follows ``COOKIE_SECURE``, else the request's scheme, which uvicorn takes from
X-Forwarded-Proto only when the proxy is one it believes (``FORWARDED_ALLOW_IPS``).
"""

from fastapi import Request, Response
from jigkit.auth import clear_session_cookie as _clear
from jigkit.auth import issue_session_cookie as _issue

from .deps import Services


def issue_session_cookie(
    response: Response, services: Services, token: str, request: Request
) -> None:
    """Log the browser in with ``token``."""
    settings = services.settings
    _issue(
        response,
        request,
        name=settings.session_cookie_name,
        token=token,
        max_age_seconds=settings.session_lifetime_hours * 3600,
        secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response, services: Services, request: Request) -> None:
    """Log the browser out."""
    _clear(
        response,
        request,
        name=services.settings.session_cookie_name,
        secure=services.settings.cookie_secure,
    )
