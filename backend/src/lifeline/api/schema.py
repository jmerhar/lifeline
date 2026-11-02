"""The app as the OpenAPI export builds it."""

from pathlib import Path

from fastapi import FastAPI

from lifeline.api.app import create_app
from lifeline.config import Settings


def build_app(data_dir: Path) -> FastAPI:
    """Build the app for exporting its schema, with its data in a scratch directory.

    Named in devtools.toml's [openapi] table. A fixed secret key keeps the export from generating
    one; building the app starts neither the scheduler nor a browser.
    """
    return create_app(Settings(data_dir=data_dir, secret_key="schema-export"))
