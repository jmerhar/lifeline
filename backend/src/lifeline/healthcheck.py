"""The container's health probe.

Exits non-zero unless the API answers and reports its database reachable. A probe that only
checked whether the port was open would call a container healthy while every request it served
failed.
"""

import json
import sys
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8000/api/health"
TIMEOUT_SECONDS = 5


def main() -> int:
    """Report whether the application is serving."""
    try:
        with urllib.request.urlopen(URL, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            # urlopen raises for 4xx and 5xx, so this only catches a 2xx that is not 200 --
            # a 204, say, which is not an answer to a health question either.
            if response.status != 200:
                print(f"unhealthy: HTTP {response.status}", file=sys.stderr)
                return 1
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        # Closed explicitly: an HTTPError carries the response it was raised from, and letting
        # it be collected unclosed emits a ResourceWarning.
        with exc:
            print(f"unhealthy: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"unhealthy: {exc}", file=sys.stderr)
        return 1

    if body.get("database") != "connected":
        print(f"unhealthy: database {body.get('database')!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
