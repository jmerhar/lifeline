"""The migrations, checked against the models they are supposed to produce."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine

from lifeline.models import Base

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_to_head(connection: Connection, database_url: str) -> None:
    """Run every migration against an open connection."""
    from alembic.runtime.environment import EnvironmentContext

    config = alembic_config(database_url)
    scripts = ScriptDirectory.from_config(config)

    def run(revision: str, context: object) -> list:
        return scripts._upgrade_revs("head", revision)

    with EnvironmentContext(config, scripts, fn=run, as_sql=False) as env:
        env.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with env.begin_transaction():
            env.run_migrations()


class TestMigrations:
    def test_produce_exactly_the_schema_the_models_describe(self, data_dir: Path) -> None:
        # The tests build their schema with create_all, so nothing else would notice a model
        # change that never got a migration — until a deployment upgraded and broke.
        database = data_dir / "migrated.db"
        engine = create_engine(f"sqlite:///{database}")
        try:
            with engine.begin() as connection:
                upgrade_to_head(connection, f"sqlite:///{database}")
            with engine.connect() as connection:
                context = MigrationContext.configure(
                    connection, opts={"compare_type": True, "render_as_batch": True}
                )
                differences = compare_metadata(context, Base.metadata)
        finally:
            engine.dispose()

        assert differences == [], (
            "the models and the migrations disagree; generate a migration with "
            "`make revision m='what changed'`"
        )

    def test_there_is_exactly_one_head(self) -> None:
        # Two heads means two migrations claim the same parent, and `upgrade head` fails on a
        # deployment rather than in CI.
        scripts = ScriptDirectory.from_config(alembic_config("sqlite:///unused.db"))

        assert len(scripts.get_heads()) == 1
