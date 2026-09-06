"""Small queries shared by the API and the scheduler."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SETTINGS_ID, Check, CheckOutcome, Setting, Site


async def load_settings_row(session: AsyncSession) -> Setting:
    """The settings row, created with its defaults if this instance has none yet.

    Created on demand rather than by a migration, so the defaults live with the model
    (where they are visible and typed) instead of being duplicated in a data migration
    that cannot be kept in step with it.
    """
    row = await session.get(Setting, SETTINGS_ID)
    if row is None:
        row = Setting(id=SETTINGS_ID)
        session.add(row)
        await session.flush()
    return row


async def get_site(session: AsyncSession, site_id: int) -> Site | None:
    """One site, with its stored session loaded."""
    return await session.get(Site, site_id)


async def list_sites(session: AsyncSession) -> list[Site]:
    """Every site, in the order the list is displayed."""
    result = await session.execute(select(Site).order_by(Site.name))
    return list(result.scalars())


async def due_sites(session: AsyncSession, now: datetime) -> list[Site]:
    """The enabled sites whose next check is due.

    A site that has never been checked has no next-check time and is due immediately,
    which is what makes a newly added site report its state without waiting an interval.
    """
    result = await session.execute(
        select(Site)
        .where(Site.enabled.is_(True))
        .where((Site.next_check_at.is_(None)) | (Site.next_check_at <= now))
        .order_by(Site.next_check_at.is_(None).desc(), Site.next_check_at)
    )
    return list(result.scalars())


async def recent_checks(session: AsyncSession, site_id: int, limit: int) -> list[Check]:
    """A site's most recent checks, newest first."""
    result = await session.execute(
        select(Check)
        .where(Check.site_id == site_id)
        .order_by(Check.started_at.desc(), Check.id.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def prune_checks(session: AsyncSession, retention_days: int, now: datetime) -> int:
    """Delete checks older than the retention window, returning how many went.

    The value of this history is the shape of the recent trend, not an audit trail, and an
    unbounded table is a slow disk-space leak on a machine nobody is watching.
    """
    if retention_days <= 0:
        return 0
    cutoff = now - timedelta(days=retention_days)
    result = await session.execute(delete(Check).where(Check.started_at < cutoff))
    return result.rowcount or 0


async def pulse_for_sites(
    session: AsyncSession, per_site: int
) -> dict[int, list[CheckOutcome]]:
    """The recent outcomes for every site, oldest first, for the pulse strip.

    One windowed query rather than one query per site: the site list renders every site's
    recent history at once, and the per-site version turns a page load into a query per row.
    """
    ranked = (
        select(
            Check.site_id,
            Check.outcome,
            func.row_number()
            .over(
                partition_by=Check.site_id,
                order_by=(Check.started_at.desc(), Check.id.desc()),
            )
            .label("position"),
        )
        .subquery()
    )
    result = await session.execute(
        select(ranked.c.site_id, ranked.c.outcome)
        .where(ranked.c.position <= per_site)
        # Descending position puts the oldest of the recent checks first, which is the
        # order the strip is drawn in.
        .order_by(ranked.c.site_id, ranked.c.position.desc())
    )
    pulse: dict[int, list[CheckOutcome]] = {}
    for site_id, outcome in result:
        pulse.setdefault(site_id, []).append(outcome)
    return pulse
