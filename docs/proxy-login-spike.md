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
afterwards. Those are the two things that decide whether this can replace the browser.

## What would have to hold

1. The login page renders well enough to use — its CSS and images load.
2. Submitting the form reaches the site and comes back, including whatever it does with JavaScript.
3. The cookies the site sets during login are captured, and a later plain ping with them is accepted.
4. Any bot-protection the site runs does not reject the request for coming from a proxy.

1 and 2 are engineering. 3 is the point. **4 is the one that can kill it**: a challenge computes a
token bound to the origin it was served from, so a token earned against
`lifeline.example.org` is not valid for the site.

## Result

Recorded below as the spike proceeds. If it fails, this file stays as the reason not to try again.
