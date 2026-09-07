"""Where the log goes, and what changes its level."""

import logging
from pathlib import Path

import pytest

from lifeline.config import Settings
from lifeline.services import logs


@pytest.fixture(autouse=True)
def restore_logging():
    """Put the root logger back, so one test's handlers are not another's."""
    root = logging.getLogger()
    before = list(root.handlers), root.level
    yield
    for handler in [h for h in root.handlers if h not in before[0]]:
        root.removeHandler(handler)
        handler.close()
    root.handlers = before[0]
    root.setLevel(before[1])


class TestConfigure:
    def test_writes_to_a_file_in_the_data_directory(self, settings: Settings) -> None:
        # The data directory is the one thing a deployment mounts, so the log can be read from the
        # host without reaching into the container.
        path = logs.configure(settings)

        logging.getLogger("lifeline.test").warning("a line worth keeping")

        assert path == settings.data_dir / "logs" / "lifeline.log"
        assert "a line worth keeping" in path.read_text()

    def test_keeps_logging_to_the_stream(self, settings: Settings) -> None:
        # `docker logs` is where the first-run setup token is printed, and it is printed nowhere
        # else — losing the stream would make a new deployment unusable.
        logs.configure(settings)

        kinds = {type(handler).__name__ for handler in logging.getLogger().handlers}

        assert "StreamHandler" in kinds
        assert "RotatingFileHandler" in kinds

    def test_bounds_the_file(self, settings: Settings) -> None:
        # Nothing rotates a file inside a container; an unbounded one is a slow disk-space leak.
        logs.configure(settings)

        handler = next(
            h for h in logging.getLogger().handlers if type(h).__name__ == "RotatingFileHandler"
        )

        assert handler.maxBytes > 0
        assert handler.backupCount > 0

    def test_calling_it_twice_does_not_log_everything_twice(self, settings: Settings) -> None:
        logs.configure(settings)
        logs.configure(settings)

        path = logs.log_path(settings)
        logging.getLogger("lifeline.test").warning("once")

        assert path.read_text().count("once") == 1

    def test_serves_on_when_the_file_cannot_be_opened(self, settings: Settings) -> None:
        # A read-only or unwritable data directory should not stop the application running.
        (settings.data_dir / "logs").write_text("this is a file, not a directory")

        assert logs.configure(settings) is None
        assert logging.getLogger().handlers

    def test_uses_the_configured_level(self, data_dir: Path) -> None:
        logs.configure(Settings(data_dir=data_dir, log_level="WARNING"))

        assert logging.getLogger().level == logging.WARNING

    def test_falls_back_to_info_for_a_level_it_does_not_know(self, data_dir: Path) -> None:
        logs.configure(Settings(data_dir=data_dir, log_level="chatty"))

        assert logging.getLogger().level == logging.INFO


class TestApplyLevel:
    def test_changes_the_root_level(self, settings: Settings) -> None:
        logs.configure(settings, level="INFO")

        logs.apply_level("DEBUG")

        assert logging.getLogger().level == logging.DEBUG

    def test_changes_the_loggers_that_hold_their_own_level(self, settings: Settings) -> None:
        # uvicorn gives its access and error loggers a level of their own, so raising the root
        # alone would leave request logging exactly where it was.
        logs.configure(settings)

        logs.apply_level("ERROR")

        assert logging.getLogger("uvicorn.access").level == logging.ERROR

    def test_a_raised_level_stops_quieter_lines_reaching_the_file(self, settings: Settings) -> None:
        path = logs.configure(settings)

        logs.apply_level("ERROR")
        logging.getLogger("lifeline.test").info("too quiet to keep")
        logging.getLogger("lifeline.test").error("loud enough")

        written = path.read_text()
        assert "too quiet to keep" not in written
        assert "loud enough" in written
