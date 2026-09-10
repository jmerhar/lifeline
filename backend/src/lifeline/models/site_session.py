"""The stored credential material for one site."""

from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, UtcDateTime
from .enums import CaptureMethod, enum_column
from .site import Site


class SiteSession(Base, TimestampMixin):
    """A captured browser session: cookies plus local storage, encrypted at rest.

    One row per site. Re-authenticating replaces it, so there is never a stale jar to
    pick by mistake.
    """

    __tablename__ = "site_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), unique=True
    )

    # Playwright storage state (cookies + origins' local storage) as encrypted JSON.
    # Encrypted because it is equivalent to being logged in: anything that can read this
    # column can use the account without the password.
    state: Mapped[bytes] = mapped_column(LargeBinary)

    captured_via: Mapped[CaptureMethod] = mapped_column(enum_column(CaptureMethod))
    captured_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # When a ping last brought back a fresh cookie for this session.
    rotated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    # When the last of the stored cookies expires — the point after which nothing held here can
    # work. The soonest would be some analytics cookie with a fifteen-minute life, which says
    # nothing about the session.
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    # Cookie names only, for display. Never the values.
    cookie_names: Mapped[str] = mapped_column(Text, default="")
    # The keys of what is held per origin — local storage, where a site that builds its page in
    # the browser keeps its session instead of in a cookie. Names only, never values.
    storage_names: Mapped[str] = mapped_column(Text, default="")

    site: Mapped[Site] = relationship(back_populates="session")
