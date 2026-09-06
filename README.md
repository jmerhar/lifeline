# lifeline

[![Test and Publish](https://github.com/jmerhar/lifeline/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/jmerhar/lifeline/actions/workflows/build-and-push.yml)
[![codecov](https://codecov.io/gh/jmerhar/lifeline/branch/main/graph/badge.svg)](https://app.codecov.io/gh/jmerhar/lifeline)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Some sites deactivate an account that goes unused for too long. Keeping one alive means
logging in by hand, on a schedule, for every site, forever — and the penalty for forgetting
is losing the account.

**lifeline** does it for you. Log into a site **once**, through a real browser embedded in
lifeline's own interface, and it then visits that site on a schedule using the session you
captured. If the session stops working, it tells you — by email, Telegram, ntfy, or anything
else [Apprise](https://github.com/caronc/apprise) can reach — while there is still time to
log in again.

![The site list](docs/screenshot-dark.png)

<sub>Each row's *pulse* is that site's last twelve checks — above the line is a good one,
below it a failure — so a session that has been dying for a week is visible without reading
anything. There is a [light theme](docs/screenshot-light.png) too.</sub>

## What it actually does

- **Captures a session once.** The login happens in a real headful Chromium, streamed into
  the page over VNC. Two-factor prompts, consent walls and bot checks all work, because it is
  a real browser and you are the one driving it.
- **Or takes cookies you already have.** Paste a `Cookie:` header, a JSON export from a
  cookie extension, or a `cookies.txt` file, and skip the browser entirely.
- **Pings on a schedule.** One authenticated request per site per interval — seven days by
  default — with the User-Agent the session was captured with, jittered so a site is never
  asked at the same time forever.
- **Keeps the session fresh.** Sessions with a sliding expiry re-issue their cookie on each
  request, and some rotate the token outright, so every response's cookies are folded back
  into what is stored. Throwing them away is how a keep-alive tool ends up being the thing
  that logs you out.
- **Notices when a session dies**, by watching for the login page, for text that only a
  logged-in page shows, and for text that only a logged-out one does.
- **Warns before a deadline.** Tell it a site disables an account after 90 days and it counts
  down, and says something while there is still time.

## Running it

```bash
git clone https://github.com/jmerhar/lifeline.git
cd lifeline
docker compose up -d
```

Then open <http://127.0.0.1:8000>. The first screen asks for a **setup token**, which is
printed in the container's log:

```bash
docker compose logs lifeline | grep "setup token"
```

That token is what stops whoever finds the URL first from claiming the instance. Create your
account and you are in.

Everything the container keeps lives in `./data` — the SQLite database, the encryption key it
generates on first boot, and one browser profile per site. Back that directory up and there
is nothing else to save.

### Configuration

Every setting has a working default; `.env.example` lists them. The ones worth knowing:

| Variable | Default | What it does |
|---|---|---|
| `LIFELINE_BIND` / `LIFELINE_PORT` | `127.0.0.1` / `8000` | Where the interface is published. The default assumes a reverse proxy in front. |
| `SETUP_TOKEN` | generated | Guards the first-run wizard. `off` disables it — only where nobody else can reach the interface. |
| `SECRET_KEY` | generated into `./data` | Encrypts the stored sessions. **Losing it means logging into every site again.** |
| `AUTH_DISABLED` | `false` | Skips lifeline's own login, for an instance already behind someone else's authentication. |
| `LIFELINE_UID` / `LIFELINE_GID` | `1000` | The user the container runs as. It must own `./data`. |

Anything holding a secret also accepts a `*_FILE` variant naming a file to read it from, for
a deployment that would rather mount secrets than pass them in the environment.

Behind a reverse proxy, forward the `Upgrade` header — the login browser is streamed over a
websocket. lifeline reads `X-Forwarded-Proto` to decide whether its session cookie is
`Secure`.

## Adding a site

Two fields matter more than the rest.

**Ping URL** must be a page that only renders *as itself* when you are logged in. A site's
home page often renders for anyone, so a check against it passes while the session is dead.
An account or settings page is usually the right choice.

**How lifeline can tell** — fill in whichever of these the site gives you:

| Field | Example | What it catches |
|---|---|---|
| Login page looks like | `login.php` | The site bounced the request to its login page. This catches most sites on its own. |
| Page must contain | `Log out` | Text only a logged-in page shows. |
| Page must not contain | `Enter your password` | Text only a logged-out page shows. |
| Expected status | `200` | A response that is not the one a good check gives. |

Then set **"site disables an account after"** if the site has such a rule, and lifeline will
count down to it and warn you in advance.

Adding the same site twice, under two names, tracks two accounts on it independently.

### When a plain request is not enough

A site that decides what to serve after running JavaScript will hand a plain request an empty
shell that proves nothing either way. Switch that site to **"a real browser"** and its checks
replay the stored session through headless Chromium instead. It costs a browser launch per
check, so it is per-site rather than the default.

If a site is behind a challenge that issues an IP-bound clearance cookie, note that the ping
goes out from the machine lifeline runs on. Log in from lifeline's own browser, not from your
laptop, or the cookie will be tied to the wrong address.

## Notifications

Settings → Notifications takes one [Apprise URL](https://github.com/caronc/apprise#supported-notifications)
per line:

```
tgram://bot-token/chat-id
mailto://user:password@smtp.example.org
ntfy://ntfy.sh/your-topic
```

**Send a test notification** proves the configuration before you need it to work. A site that
has just lapsed is reported once and then stays quiet for a cooldown, so one dead session
cannot become a message per check.

## Development

```bash
make install       # backend virtualenv + frontend packages
make browser       # the Chromium build the login browser drives
make dev           # API on :8000 with reload, interface on :5173
make check         # lint, both test suites, and the coverage gate
```

`make help` lists everything. The tests that drive a real browser are skipped unless one is
installed; to include the interactive-login ones, start an X server and point
`LIFELINE_TEST_DISPLAY` at it (`Xvfb :99 &`, then `LIFELINE_TEST_DISPLAY=:99`).

| Layer | Built with |
|---|---|
| Backend | Python 3.14, FastAPI, SQLAlchemy 2.0 (async), Alembic, SQLite |
| Login browser | Playwright Chromium, headful under Xvfb, streamed via x11vnc and noVNC |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query |
| Notifications | Apprise |

## A note on what this holds

A captured session is equivalent to being logged in: anything that can read it can use the
account without the password. So the sessions are encrypted in the database, the interface has
its own password, and the container publishes to loopback by default. If you expose it to the
internet, its password is the only thing between the two — choose accordingly.

lifeline sends **one request per site per interval**. Please leave it that way: a keep-alive
tool has no reason to generate more traffic than the account needs, and some sites are
entitled to object.

## Licence

[GPL-3.0](LICENSE).
