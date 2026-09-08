"""Managing sites, their sessions and their history."""

from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from ...models import CaptureMethod, Setting, Site, SiteStatus
from ...schemas import (
    CheckRead,
    CookieImport,
    DetectedRules,
    LoginSessionRead,
    Message,
    SessionRead,
    SiteRead,
    SiteWrite,
)
from ...services import favicon
from ...services.browser.driver import VIEWPORT_HEIGHT, VIEWPORT_WIDTH
from ...services.browser.manager import BrowserUnavailable
from ...services.checker import is_at_risk
from ...services.cookies import CookieParseError, parse_import
from ...services.store import (
    get_site,
    list_sites,
    load_settings_row,
    pulse_for_sites,
    recent_checks,
)
from ..deps import DbDep, ServicesDep, require_setup_complete, require_user

router = APIRouter(
    prefix="/sites",
    tags=["sites"],
    dependencies=[Depends(require_setup_complete), Depends(require_user)],
)

# How many recent checks the pulse strip shows.
PULSE_LENGTH = 12
# The default page of history for one site.
HISTORY_LENGTH = 50


def _risk(site: Site, settings_row: Setting, now: datetime) -> str | None:
    """Why a site needs attention, for the statuses where that is the open question.

    A lapsed or erroring site has already been reported as such, and telling someone that its
    account lapses in two days describes a race it has lost. Mirrors what the scheduler considers.
    """
    if site.status not in (SiteStatus.ALIVE, SiteStatus.AT_RISK):
        return None
    return is_at_risk(site, settings_row, now=now)


def to_read(site: Site, pulse: list[str] | None = None, risk: str | None = None) -> SiteRead:
    """Render a site for the API, with its derived fields."""
    stored = site.session
    session = None
    if stored is not None:
        session = SessionRead(
            captured_at=stored.captured_at,
            captured_via=stored.captured_via,
            rotated_at=stored.rotated_at,
            expires_at=stored.expires_at,
            cookie_names=[name for name in stored.cookie_names.split(",") if name],
        )
    return SiteRead(
        id=site.id,
        name=site.name,
        ping_url=site.ping_url,
        login_url=site.login_url,
        enabled=site.enabled,
        interval_days=site.interval_days,
        jitter_percent=site.jitter_percent,
        ping_method=site.ping_method,
        user_agent=site.user_agent,
        favicon=site.favicon,
        expected_status=site.expected_status,
        follow_redirects=site.follow_redirects,
        login_url_pattern=site.login_url_pattern,
        success_pattern=site.success_pattern,
        failure_pattern=site.failure_pattern,
        inactivity_limit_days=site.inactivity_limit_days,
        notes=site.notes,
        status=site.status,
        consecutive_failures=site.consecutive_failures,
        last_check_at=site.last_check_at,
        last_ok_at=site.last_ok_at,
        next_check_at=site.next_check_at,
        deadline_at=site.deadline_at,
        session=session,
        pulse=pulse or [],
        risk=risk,
    )


async def load_site(db: DbDep, site_id: int) -> Site:
    site = await get_site(db, site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such site")
    return site


@router.get("")
async def index(db: DbDep) -> list[SiteRead]:
    """Every site, with the recent history the list displays."""
    sites = await list_sites(db)
    pulse = await pulse_for_sites(db, PULSE_LENGTH)
    row = await load_settings_row(db)
    now = datetime.now(UTC)
    return [to_read(site, pulse.get(site.id, []), risk=_risk(site, row, now)) for site in sites]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(payload: SiteWrite, db: DbDep, services: ServicesDep) -> SiteRead:
    """Add a site."""
    if await _name_taken(db, payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="a site with that name already exists"
        )
    site = Site(**payload.model_dump())
    # A new site has no captured session. Stated rather than left unset, because reading an
    # unset relationship would send SQLAlchemy off to load it during attribute access, which
    # its async session cannot do.
    site.session = None
    site.favicon = await _fetch_icon(services, site.ping_url)
    db.add(site)
    await db.flush()
    return to_read(site)


@router.get("/{site_id}")
async def show(site_id: int, db: DbDep) -> SiteRead:
    """One site."""
    site = await load_site(db, site_id)
    pulse = await pulse_for_sites(db, PULSE_LENGTH)
    row = await load_settings_row(db)
    return to_read(site, pulse.get(site.id, []), risk=_risk(site, row, datetime.now(UTC)))


@router.put("/{site_id}")
async def update(site_id: int, payload: SiteWrite, db: DbDep, services: ServicesDep) -> SiteRead:
    """Change a site's configuration."""
    site = await load_site(db, site_id)
    if payload.name != site.name and await _name_taken(db, payload.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="a site with that name already exists"
        )
    previous_url = site.ping_url
    for field, value in payload.model_dump().items():
        setattr(site, field, value)
    if site.ping_url != previous_url or not site.favicon:
        site.favicon = await _fetch_icon(services, site.ping_url)
    await db.flush()
    return to_read(site)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def destroy(site_id: int, db: DbDep) -> None:
    """Remove a site, its stored session and its history."""
    site = await load_site(db, site_id)
    await db.delete(site)


@router.get("/{site_id}/checks")
async def history(site_id: int, db: DbDep, limit: int = HISTORY_LENGTH) -> list[CheckRead]:
    """A site's recent checks, newest first."""
    await load_site(db, site_id)
    checks = await recent_checks(db, site_id, min(max(limit, 1), 500))
    return [CheckRead.model_validate(check) for check in checks]


@router.post("/{site_id}/check")
async def check_now(site_id: int, db: DbDep, services: ServicesDep) -> CheckRead:
    """Ping a site immediately and return the result."""
    await load_site(db, site_id)
    # Committed before handing over: the runner works in its own session, and an uncommitted
    # change here would not be visible to it.
    await db.commit()
    check = await services.runner.run(site_id)
    if check is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no such site")
    return CheckRead.model_validate(check)


@router.post("/{site_id}/detect")
async def detect(site_id: int, db: DbDep, services: ServicesDep) -> DetectedRules:
    """Work out how to tell this site's live session from a dead one.

    Fetches the ping URL twice, once with the stored session and once with no cookies, and
    reports what differs. Needs a session, because half the comparison is what the page looks
    like to somebody who is logged in.
    """
    site = await load_site(db, site_id)
    if site.session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="log in to this site first — there is nothing to compare a logged-out page to",
        )
    state = services.cipher.decrypt_json(site.session.state)
    try:
        found = await services.detector.detect(site, state)
    except BrowserUnavailable as exc:
        # A site set to be checked through a browser is compared through one too, so a
        # deployment without one cannot answer for it at all.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could not reach the site: {exc}",
        ) from exc
    return DetectedRules(
        login_url=found.login_url,
        login_url_pattern=found.login_url_pattern,
        success_pattern=found.success_pattern,
        failure_pattern=found.failure_pattern,
        notes=found.notes,
    )


@router.post("/{site_id}/session/import")
async def import_session(
    site_id: int, payload: CookieImport, db: DbDep, services: ServicesDep
) -> Message:
    """Store a session pasted in by hand."""
    site = await load_site(db, site_id)
    try:
        state = parse_import(payload.text, site.ping_url)
    except CookieParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    await db.commit()
    await services.runner.store_session(
        site_id, state, CaptureMethod.IMPORT, user_agent=payload.user_agent
    )
    return Message(detail="session imported")


@router.post("/{site_id}/login-session")
async def open_login(site_id: int, db: DbDep, services: ServicesDep) -> LoginSessionRead:
    """Start a browser at the site's login page and stream its screen."""
    site = await load_site(db, site_id)
    row = await load_settings_row(db)
    try:
        session = await services.browser.open_login(
            site_id,
            site.effective_login_url,
            timedelta(minutes=row.browser_idle_timeout_minutes),
            # A site with nothing stored is being logged into for the first time, so the browser
            # starts with an empty cookie jar: landing already signed in as another account is
            # how the wrong session gets captured without anyone noticing.
            signed_out=site.session is None,
        )
    except BrowserUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return LoginSessionRead(
        site_id=site_id,
        ws_path=f"/api/browser/{session.token}/ws",
        width=VIEWPORT_WIDTH,
        height=VIEWPORT_HEIGHT,
        expires_at=session.expires_at,
    )


@router.delete("/{site_id}/session")
async def forget_session(site_id: int, db: DbDep) -> Message:
    """Discard a site's stored session."""
    site = await load_site(db, site_id)
    if site.session is not None:
        await db.delete(site.session)
    # Nothing to do about the login browser: it shares one profile between every site, so
    # wiping it would take the extension setup with it. Discarding the stored session is what
    # makes the next login for this site open with an empty cookie jar, which reaches the same
    # place — the site is asked for as somebody signed out.
    return Message(detail="session discarded")


async def _name_taken(db: DbDep, name: str) -> bool:
    from sqlalchemy import select

    result = await db.execute(select(Site.id).where(Site.name == name))
    return result.first() is not None


async def _fetch_icon(services: ServicesDep, url: str) -> str | None:
    """Best-effort icon fetch, which must never stop a site being saved."""
    async with httpx.AsyncClient(
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": services.settings.default_user_agent},
    ) as client:
        return await favicon.fetch(url, client=client)



