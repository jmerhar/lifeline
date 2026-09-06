#!/usr/bin/env python
"""Print the application's OpenAPI schema.

Built from the app itself rather than written by hand, so the schema cannot describe a
response the code does not actually return. Nothing is connected to: constructing the app
builds an engine but opens no connection, and this only asks it for its routes.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from lifeline.api.app import create_app  # noqa: E402
from lifeline.config import Settings  # noqa: E402


def main() -> None:
    """Write the schema to stdout."""
    with tempfile.TemporaryDirectory() as scratch:
        # A throwaway data directory: building the app generates an encryption key if none
        # exists, and exporting a schema has no business writing one into a real deployment.
        app = create_app(
            Settings(data_dir=Path(scratch), secret_key="schema-export", scheduler_enabled=False)
        )
        json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
