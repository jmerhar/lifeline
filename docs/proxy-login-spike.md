# Spike: logging in through lifeline instead of through a browser inside it

## What this is testing

Today an interactive login runs a headful Chromium on the server and streams its screen. That
browser is not yours, so your password manager cannot reach it and a hardware key is impossible, and
it is what makes the image 2 GB.

The alternative is to put lifeline in the middle instead of a browser: it proxies the site's login
pages to **your** browser, and keeps the cookies the site hands out. Your password manager works
because the page is in your own browser. The image loses Chromium entirely.

The question this spike answers is not "can a proxy serve a page" — it can. It is whether a real
site's login **completes** through one, and whether the session captured that way actually works
afterwards.

## What would have to hold

1. The login page renders well enough to use — its CSS and images load.
2. Submitting the form reaches the site and comes back, including whatever it does with JavaScript.
3. The cookies the site sets during login are captured, and a later plain ping with them is accepted.
4. Any bot-protection the site runs does not reject the request for coming from a proxy.

## Result: viable for server-rendered logins, with one blocking change first

All four hold for the shape of login this tool mostly deals with — a server-rendered form. Proven,
not assumed: `test_proxy_in_a_browser.py` drives a real browser through the whole flow, and the
session lifeline keeps at the end is then used by a plain HTTP client to fetch a page that only
renders when logged in.

| | |
|---|---|
| 1. Renders | **Yes.** Markup and CSS URLs are rewritten back through lifeline; third-party ones are left alone. |
| 2. Submits | **Yes** for a form post, verified in Chromium — including the redirect, which stays inside the proxy. **No** for a login submitted over XHR (below). |
| 3. Session usable | **Yes.** This is the one that mattered, and it works. |
| 4. Bot protection | **Not triggered** by any of the four real sites sampled — each returned its real login page to a plain server-side fetch, the Cloudflare-fronted one included. |

### The blocking finding: it must not share lifeline's origin

A proxied page is served from lifeline's own origin, so its JavaScript is same-origin with lifeline's
API. `test_the_proxied_page_can_call_lifelines_own_api` demonstrates the consequence: a script on the
proxied page calls `/api/sites` with credentials and gets a 200 and the data. `HttpOnly` does not
help — the browser sends the cookie because the request *is* same-origin — and neither does
`SameSite`.

So any script on any login page it serves could read and change everything lifeline holds, including
`/api/settings`, which carries the notification credential.

This is fixable, but not by patching: proxied content has to come from **a different origin** — its
own hostname, so the browser treats it as a foreign site. On a host with a wildcard certificate that
is one more vhost entry. Nothing should ship until that is how it works.

### What else it cannot do

- **Logins submitted over XHR.** `fetch('/api/login')` is a URL JavaScript builds at runtime; the
  proxy rewrites what the markup declares and nothing else, so it resolves against lifeline's root
  and the submission never reaches the site. Rewriting JavaScript by regular expression would trade
  a visible failure for an unpredictable one, so it is left alone — and a site of this shape has to
  be detected and refused rather than half-served.
- **A login that hops to another host** — an SSO redirect to `auth.example.com` — leaves the proxied
  origin and escapes it. It would need a jar per host and a way to decide which hosts to follow.
- **Hardware keys and passkeys.** WebAuthn is bound to the origin, so a token earned against
  lifeline's hostname is worthless to the site. No remote-login scheme can fix this; the browser
  panel cannot either, because it has no access to the key. Such a site has to be logged into on
  your own machine, with **Paste cookies**.
- **It works by removing protections the site asked for.** `Content-Security-Policy` and
  `X-Frame-Options` are stripped, because they exist to stop exactly this.

## What shipping it as a slim image would take

1. Serve proxied content from its own origin. Blocking; see above.
2. Give the proxy a lifetime. It currently lives in a process-global dictionary with no expiry and no
   single-flight — the spike's shortcut, and the reason this is not mergeable as it stands.
3. Detect an XHR login and say so, rather than serving a page whose submit button does nothing.
4. A tab in the login panel, alongside the browser and the paste routes.
5. Decide what the browser image and the slim image each promise, so a site that needs the browser is
   not silently unsupported on the slim one.

Steps 1 and 2 are the real work. Everything else is presentation.
