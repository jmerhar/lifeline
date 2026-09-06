# lifeline

## What this is

A self-hosted tool that keeps logged-in website sessions alive. You log into a site once
through a browser embedded in lifeline's own interface; it then pings that site on a schedule
with the captured session, and notifies you through Apprise when a session stops working.

## Layout

```
backend/src/lifeline/
  config.py            settings; every secret also accepts a *_FILE variant
  models/              SQLAlchemy models; UtcDateTime keeps every datetime aware
  schemas.py           the API's request and response shapes
  api/                 FastAPI app, dependencies, security, routers
  services/
    checker.py         performs a ping and decides the verdict   ← the core
    cookies.py         parses imports, and merges Set-Cookie back into storage
    runner.py          applies a check to the database and reacts to it
    scheduler.py       the due-loop, risk refresh and history pruning
    notifier.py        Apprise fan-out, with per-site cooldowns
    crypto.py          encrypts stored sessions
    browser/           supervisor, driver, manager, VNC bridge, fetcher
frontend/src/          React + TypeScript interface
bin/                   every script the Makefile and CI run
```

## Things worth knowing before changing anything

- **Response cookies must be written back after every ping.** A session with a sliding expiry
  re-issues its cookie on each request and some schemes rotate the token outright, so
  discarding the response's cookies either throws away the extension the ping just earned or
  invalidates the session outright. `merge_jar_into_state` exists for this.
- **httpx copies a `Cookies` instance** when it is handed to a client, so the jar passed in
  never sees `Set-Cookie`. Read `client.cookies` after the request. Getting this wrong looks
  exactly like a site that does not rotate its cookies.
- **A marker matched against `/proc/*/cmdline` must have its NULs replaced with spaces**, or
  any marker containing a space matches nothing and every "is it gone?" check silently
  passes. See `browser/supervisor.py`.
- **Child processes are started in their own process group and killed as a group, and the
  kill is then verified.** A leaked headful Chromium grows until the host is swapping, and
  nothing about the failure is loud.
- **`Setting()` built in Python has `None` in every column** — SQLAlchemy applies column
  defaults on insert, not on construction. Tests use `tests/conftest.make_settings()`, and
  `test_defaults_match_the_model` keeps the two in step.
- **The Playwright driver reads its User-Agent from the first request the browser makes**,
  not by evaluating JavaScript in the page: evaluation fails outright mid-navigation, which
  is exactly when someone presses Save.
- **`SiteStatus.AT_RISK` is recomputed on every scheduler tick**, not only after a check.
  Both clocks that can run out — the site's inactivity deadline and a cookie's expiry — do so
  without anything failing.

## Commands

```bash
make install         # backend virtualenv + frontend packages
make browser         # the Chromium build the login browser drives
make dev             # hot-reload stack: API on :8000, interface on :5173
make check           # lint + both suites + the coverage gate
make test-backend ARGS="tests/test_services/test_checker.py -k redirect"
make revision m="what changed"   # generate a migration from the models
```

The tests that drive a real browser are skipped unless Chromium is installed; the headful
ones also need `LIFELINE_TEST_DISPLAY` pointed at an X display.

## Testing conventions

- Two coverage suites, backend and frontend, with their gates in `coverage.toml`.
- The browser, Apprise and the network are all replaced by stand-ins in the ordinary suite —
  `tests/conftest.py` holds them. `tests/test_integration/` is the exception and drives the
  real thing.
- A test asserting an HTTP call must mock it; `tests/test_api/conftest.py` fails any test that
  reaches the network.
- `test_migrations.py` fails if the models and the migrations disagree, because everything
  else builds its schema with `create_all` and would not notice.
