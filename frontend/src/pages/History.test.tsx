/** The history screen. */

import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { History } from "./History";
import { makeCheck, makeSite } from "../test/factories";
import { render } from "../test/render";
import { server } from "../test/server";

describe("History", () => {
  it("names the site each check belongs to", async () => {
    render(<History />);

    expect(await screen.findByText("example")).toBeInTheDocument();
  });

  it("says in words what each outcome means", async () => {
    server.use(
      http.get("/api/checks", () =>
        HttpResponse.json([makeCheck({ outcome: "login_expired", detail: "landed on /login.php" })]),
      ),
    );

    render(<History />);

    expect(await screen.findByText(/session expired/)).toBeInTheDocument();
    expect(screen.getByText("landed on /login.php")).toBeInTheDocument();
  });

  it("falls back to the id for a site that has since been deleted", async () => {
    server.use(
      http.get("/api/checks", () => HttpResponse.json([makeCheck({ site_id: 99 })])),
      http.get("/api/sites", () => HttpResponse.json([makeSite()])),
    );

    render(<History />);

    expect(await screen.findByText("site 99")).toBeInTheDocument();
  });

  it("shows a dash where a check has no timing", async () => {
    server.use(
      http.get("/api/checks", () =>
        HttpResponse.json([makeCheck({ duration_ms: null, status_code: null })]),
      ),
    );

    render(<History />);
    await screen.findByText("example");

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("invites nothing when there is no history yet", async () => {
    server.use(http.get("/api/checks", () => HttpResponse.json([])));

    render(<History />);

    expect(await screen.findByText(/No checks yet/)).toBeInTheDocument();
  });

  it("says so when the history cannot be loaded", async () => {
    server.use(
      http.get("/api/checks", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    );

    render(<History />);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  });
});
