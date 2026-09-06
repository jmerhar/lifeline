/** The API client's handling of the three answers every screen has to react to. */

import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { api, ApiError, NotAuthenticated, SetupRequired } from "./client";
import { server } from "../test/server";

describe("client", () => {
  it("returns the parsed body", async () => {
    expect(await api.me()).toMatchObject({ username: "jure" });
  });

  it("recognises an instance that has not been set up", async () => {
    // Distinct from any other 409 so the app can show the wizard rather than an error.
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json({ detail: "setup_required" }, { status: 409 }),
      ),
    );

    await expect(api.sites()).rejects.toBeInstanceOf(SetupRequired);
  });

  it("treats another conflict as an ordinary error", async () => {
    server.use(
      http.post("/api/sites", () =>
        HttpResponse.json({ detail: "a site with that name already exists" }, { status: 409 }),
      ),
    );

    await expect(api.createSite({} as never)).rejects.toThrow("already exists");
  });

  it("recognises a session that has gone", async () => {
    server.use(
      http.get("/api/sites", () => HttpResponse.json({ detail: "nope" }, { status: 401 })),
    );

    await expect(api.sites()).rejects.toBeInstanceOf(NotAuthenticated);
  });

  it("carries the API's own message on an error", async () => {
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json({ detail: "no such site" }, { status: 404 }),
      ),
    );

    await expect(api.sites()).rejects.toThrow("no such site");
  });

  it("flattens a validation error into something readable", async () => {
    // FastAPI answers with a list of per-field objects; rendering it raw would put
    // "[object Object]" in front of someone who mistyped a URL.
    server.use(
      http.post("/api/sites", () =>
        HttpResponse.json(
          { detail: [{ loc: ["body", "ping_url"], msg: "must be an http:// or https:// URL" }] },
          { status: 422 },
        ),
      ),
    );

    await expect(api.createSite({} as never)).rejects.toThrow("must be an http:// or https:// URL");
  });

  it("falls back to the status text when the body is not JSON", async () => {
    server.use(
      http.get("/api/sites", () => new HttpResponse("<html>gateway error</html>", { status: 502 })),
    );

    await expect(api.sites()).rejects.toBeInstanceOf(ApiError);
  });

  it("returns nothing for a no-content response", async () => {
    server.use(http.delete("/api/sites/1", () => new HttpResponse(null, { status: 204 })));

    await expect(api.deleteSite(1)).resolves.toBeUndefined();
  });

  it("sends JSON with the right content type", async () => {
    let contentType: string | null = null;
    server.use(
      http.post("/api/auth/login", ({ request }) => {
        contentType = request.headers.get("content-type");
        return HttpResponse.json({ id: 1, username: "jure", last_login_at: null });
      }),
    );

    await api.login({ username: "jure", password: "secret" });

    expect(contentType).toContain("application/json");
  });

  it("caps how much history it asks for", async () => {
    let url = "";
    server.use(
      http.get("/api/sites/1/checks", ({ request }) => {
        url = request.url;
        return HttpResponse.json([]);
      }),
    );

    await api.siteChecks(1, 25);

    expect(url).toContain("limit=25");
  });
});
