"""Setting and clearing the browser's login cookie."""

from fastapi import Request, Response

from .deps import Services


def _secure_for(request: Request, services: Services) -> bool:
    """Whether the cookie should be marked Secure.

    Follows the scheme the request actually arrived on unless a deployment overrides it, so
    that an instance behind a TLS-terminating proxy gets a Secure cookie while one reached
    over plain HTTP on a private network can still log in at all — a Secure cookie is
    discarded by the browser there, which looks exactly like a rejected password.
    """
    override = services.settings.cookie_secure
    if override is not None:
        return override
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


def issue_session_cookie(
    response: Response, services: Services, user_id: int, request: Request
) -> None:
    """Log the browser in."""
    settings = services.settings
    response.set_cookie(
        settings.session_cookie_name,
        services.cookies.issue(user_id),
        max_age=settings.session_lifetime_hours * 3600,
        httponly=True,
        secure=_secure_for(request, services),
        # Lax rather than Strict: the cookie must survive following a link into the UI from
        # a notification, which Strict would refuse.
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, services: Services) -> None:
    """Log the browser out."""
    response.delete_cookie(services.settings.session_cookie_name, path="/")
