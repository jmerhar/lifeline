# Changelog

Every release of lifeline, newest first. The image is `ghcr.io/jmerhar/lifeline`, and
`docker-compose.yml` pins the release line. Versions follow semantic versioning: a release that
needs something done by whoever runs it says what under **Upgrading**. Before 1.0, a minor release
may.

## Unreleased

### Added

- A footer names the version running and, for an image built by CI, links the commit it was
  built from.

### Changed

- The image built from every change to the main branch is tagged `edge`, as other images built
  on jigkit are, rather than `latest`. A deployment that followed `latest` should follow `edge`
  or a release line such as `0.1`.

## 0.1.0 — 2026-11-03

The first versioned release. Until now the image was published only as `latest`, from every
change to the main branch.

### Added

- Keeping logged-in website sessions alive: a session captured once, by logging in through a real
  browser streamed into the page or by pasting cookies, then visited on a schedule with the
  User-Agent it was captured with, its refreshed cookies kept.
- Telling a session that has died, by the login page or by text only a logged-in or a logged-out
  page shows, and warning through Apprise before a site's inactivity deadline.
- Bitwarden inside the image's browser, and a field that sends text across to it.
- Logins kept in the database, so logging out ends the session for good rather than leaving a
  signed cookie valid until it expires.
- Every write needs the interface's header and, with an Origin, the app's own; every response
  carries security headers: no content-type sniffing, a same-origin referrer, and no framing by
  other sites.

### Upgrading

- For an installation that ran the `latest` image: everyone is logged out once, since logins
  move from a signed cookie into the database. `SECRET_KEY` still protects the stored website
  sessions and is unchanged.
- First-run setup needs no token any more; a `SETUP_TOKEN` setting is ignored and can be removed.
- `docker-compose.yml` pins the release line `ghcr.io/jmerhar/lifeline:0.1` rather than `latest`.
- The image checks its own health with `python -m jigkit.healthcheck`. A compose file that
  overrides the health check with `python -m lifeline.healthcheck` should drop the override, as
  that module is gone.
