"""A browser's login to lifeline itself."""

from jigkit.auth.sessions import SessionMixin
from jigkit.models import Base
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .user import User


class LoginSession(SessionMixin, Base):
    """One logged-in browser. Only a hash of its token is kept, so the table cannot be replayed.

    Not to be confused with ``SiteSession``, the captured login to a monitored site.
    """

    __tablename__ = "login_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    user: Mapped[User] = relationship(lazy="joined")
