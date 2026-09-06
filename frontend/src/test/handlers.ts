/**
 * The default mock API: one site, set up, logged in.
 *
 * A test that cares about another state overrides the handler it needs rather than
 * rebuilding the set, so what a test is actually about stays visible in the test.
 */

import { http, HttpResponse } from "msw";

import { makeCheck, makeSettings, makeSite } from "./factories";

export const handlers = [
  http.get("/api/auth/me", () =>
    HttpResponse.json({ id: 1, username: "jure", last_login_at: null }),
  ),
  http.post("/api/auth/login", () =>
    HttpResponse.json({ id: 1, username: "jure", last_login_at: null }),
  ),
  http.post("/api/auth/logout", () => HttpResponse.json({ detail: "logged out" })),
  http.get("/api/setup", () =>
    HttpResponse.json({ setup_required: false, token_required: true }),
  ),
  http.get("/api/sites", () => HttpResponse.json([makeSite()])),
  http.get("/api/settings", () => HttpResponse.json(makeSettings())),
  http.get("/api/checks", () => HttpResponse.json([makeCheck()])),
];

/** The API answering "nobody has configured this instance yet". */
export const setupRequired = [
  http.get("/api/auth/me", () => HttpResponse.json({ detail: "setup_required" }, { status: 409 })),
  http.get("/api/setup", () =>
    HttpResponse.json({ setup_required: true, token_required: true }),
  ),
];

/** The API answering "you are not logged in". */
export const loggedOut = [
  http.get("/api/auth/me", () =>
    HttpResponse.json({ detail: "not authenticated" }, { status: 401 }),
  ),
];
