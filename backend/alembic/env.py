"""Alembic environment: jigkit's, pointed at lifeline's database and models.

jigkit runs the migrations through the application's own engine and settings, with SQLite's
foreign keys off while a table is rebuilt (so rebuilding ``sites`` keeps its checks and
sessions) and checked afterwards.
"""

from jigkit.migrations import run_migrations

from lifeline.config import get_settings
from lifeline.models import Base

run_migrations(get_settings().resolved_database_url, Base.metadata)
