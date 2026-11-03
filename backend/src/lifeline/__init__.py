"""Keep logged-in website sessions alive with scheduled pings."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("lifeline")
except PackageNotFoundError:  # pragma: no cover - only when run from a tree that is not installed
    __version__ = "0.0.0"
