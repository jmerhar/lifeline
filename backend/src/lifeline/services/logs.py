"""Where the application's log goes.

Two destinations, deliberately. The stream is what ``docker logs`` shows, and the first-run
setup token is only ever printed there — losing it would make a new deployment unusable. The
file is what survives a container being recreated, and it lives in the mounted data directory so
it can be read from the host without reaching into the container.

The level is a runtime setting rather than only an environment variable, because the moment you
need DEBUG is the moment something is failing, and restarting the container to get it loses
whatever state was interesting.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..config import Settings

FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"

# Bounded at five files of five megabytes. Docker rotates the stream for us; nothing rotates a
# file inside a container, and an unbounded log on a home server is a slow disk-space leak.
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

# Marks the handlers this module installed, so repeated calls replace them rather than stacking a
# second copy that logs every line twice.
_MARKER = "lifeline"


def log_path(settings: Settings) -> Path:
    """Where the log file is written."""
    return settings.data_dir / "logs" / "lifeline.log"


def configure(settings: Settings, level: str | None = None) -> Path | None:
    """Install the stream and file handlers, and return the file's path.

    Idempotent: calling it again re-points the handlers rather than adding more. Returns None if
    the file could not be opened — a read-only or unwritable data directory should not stop the
    application serving, and the stream still carries everything.
    """
    root = logging.getLogger()
    root.setLevel(_resolve(level or settings.log_level))

    for handler in [h for h in root.handlers if getattr(h, _MARKER, False)]:
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(FORMAT)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    _mark(stream)
    root.addHandler(stream)

    path = log_path(settings)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError:
        logging.getLogger(__name__).warning(
            "could not open %s for writing; logging to the stream only", path, exc_info=True
        )
        return None

    file_handler.setFormatter(formatter)
    _mark(file_handler)
    root.addHandler(file_handler)
    return path


def apply_level(level: str) -> None:
    """Change the level of everything that is already logging.

    Set on the root logger and on the loggers that hold their own level — uvicorn gives its
    access and error loggers one of their own, so raising the root alone would leave request
    logging where it was.
    """
    resolved = _resolve(level)
    logging.getLogger().setLevel(resolved)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx"):
        logging.getLogger(name).setLevel(resolved)


def _resolve(level: str) -> int:
    """The numeric level for a name, defaulting to INFO for anything unrecognised."""
    return getattr(logging, level.strip().upper(), logging.INFO)


def _mark(handler: logging.Handler) -> None:
    setattr(handler, _MARKER, True)
