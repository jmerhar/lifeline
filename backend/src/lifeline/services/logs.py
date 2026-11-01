"""Where the application's log goes, through jigkit's logging setup.

Two destinations. The stream is what ``docker logs`` shows, and the first-run setup token is only
ever printed there; losing it would make a new deployment unusable. The file lives in the mounted
data directory, so it survives the container being recreated and can be read from the host.

The level is a runtime setting rather than only an environment variable, because the moment you
need DEBUG is the moment something is failing, and restarting the container to get it loses
whatever state was interesting. HTTP client loggers stay at WARNING however low it goes: httpcore
logs response headers at DEBUG, and a site that re-issues its session cookie on every request
would otherwise write a live credential into the log file.
"""

from pathlib import Path

from jigkit.logging import LEVELS, apply_level, configure_logging

from ..config import Settings

__all__ = ["LEVELS", "apply_level", "configure", "log_path"]


def log_path(settings: Settings) -> Path:
    """Where the log file is written."""
    return settings.data_dir / "logs" / "lifeline.log"


def configure(settings: Settings, level: str | None = None) -> Path | None:
    """Install the stream and file handlers, and return the file's path.

    Idempotent. Returns None if the file could not be opened: an unwritable data directory does
    not stop the application serving, and the stream still carries everything.
    """
    return configure_logging(level or settings.log_level, log_file=log_path(settings))
