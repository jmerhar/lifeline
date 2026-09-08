"""SPIKE: the route that serves a site's login through lifeline. See services/proxy.py.

Everything under ``/login-proxy/{site_id}/`` is fetched from the site and handed to the browser with
its links pointing back here. The cookies the site sets are kept server-side, and ``/finish`` stores
them as the site's session — the same thing a browser login produces, reached without a browser.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...models import CaptureMethod
from ...schemas import Message
from ...services.proxy import LoginProxy, origin_of
from ..deps import DbDep, ServicesDep, require_setup_complete, require_user
from .sites import load_site

router = APIRouter(
    prefix="/login-proxy",
    tags=["login-proxy"],
    dependencies=[Depends(require_setup_complete), Depends(require_user)],
)

# One proxy per site, held for the length of the process. A spike's shortcut: it is the browser
# manager's single-session-at-a-time rule without the lifetime handling, and it is why this is not
# ready to ship.
_PROXIES: dict[int, LoginProxy] = {}


def _proxy_for(site_id: int, user_agent: str) -> LoginProxy:
    if site_id not in _PROXIES:
        _PROXIES[site_id] = LoginProxy(user_agent=user_agent)
    return _PROXIES[site_id]


@router.post("/{site_id}/finish")
async def finish(site_id: int, db: DbDep, services: ServicesDep) -> Message:
    """Store what the login earned as the site's session."""
    await load_site(db, site_id)
    proxy = _PROXIES.get(site_id)
    if proxy is None or not list(proxy.cookies.jar):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="nothing has been captured for that site yet",
        )

    from ...services.cookies import empty_state, merge_jar_into_state

    state, _ = merge_jar_into_state(empty_state(), proxy.cookies)
    await db.commit()
    await services.runner.store_session(
        site_id, state, CaptureMethod.IMPORT, user_agent=services.settings.default_user_agent
    )
    del _PROXIES[site_id]
    return Message(detail="session captured")


@router.api_route(
    "/{site_id}/{path:path}",
    methods=["GET", "POST"],
    include_in_schema=False,
)
async def through(site_id: int, path: str, request: Request, db: DbDep, services: ServicesDep):
    """Fetch one of the site's pages and hand it to the browser."""
    site = await load_site(db, site_id)
    origin = origin_of(site.effective_login_url)
    proxy = _proxy_for(site_id, services.settings.default_user_agent)

    target = f"/{path}" if not path.startswith("/") else path
    if request.url.query:
        target = f"{target}?{request.url.query}"

    answer = await proxy.forward(
        origin=origin,
        path=target,
        prefix=f"/api/login-proxy/{site_id}",
        method=request.method,
        body=await request.body(),
        headers=dict(request.headers),
    )
    return Response(
        content=answer.body, status_code=answer.status_code, headers=answer.headers
    )
