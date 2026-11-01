"""The migrations, checked through jigkit's migration checks.

Each check runs ``alembic`` in a subprocess from the backend directory, exactly as the container's
entrypoint does, so lifeline's own env.py and settings are what is tested.
"""

from pathlib import Path

from jigkit.testing.migrations import MigrationProject

from lifeline.models import Base

PROJECT = MigrationProject(
    Path(__file__).resolve().parents[2],
    database_filename="lifeline.db",
    env={"SECRET_KEY": "test-secret-key"},
)


class TestMigrations:
    def test_produce_exactly_the_schema_the_models_describe(self, data_dir: Path) -> None:
        # The tests build their schema with create_all, so nothing else would notice a model
        # change that never got a migration. Fix a failure with `make revision m='what changed'`.
        PROJECT.assert_models_match(Base.metadata, data_dir)

    def test_there_is_exactly_one_head(self) -> None:
        PROJECT.assert_single_head()

    def test_rebuilding_a_table_keeps_the_rows_pointing_at_it(
        self, data_dir: Path, tmp_path: Path
    ) -> None:
        # Rebuilding sites must keep its checks and stored sessions, which ON DELETE CASCADE
        # would delete if foreign keys were on during the rebuild.
        PROJECT.assert_parent_rebuilds_keep_children(Base.metadata, data_dir, tmp_path)
