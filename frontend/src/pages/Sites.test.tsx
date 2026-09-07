/** The main screen: what it shows, and what the buttons do. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { Sites } from "./Sites";
import { makeSite } from "../test/factories";
import { render } from "../test/render";
import { server } from "../test/server";

describe("Sites", () => {
  it("lists a site with its state and host", async () => {
    render(<Sites />);

    expect(await screen.findByText("example")).toBeInTheDocument();
    expect(screen.getByText("example.org")).toBeInTheDocument();
    expect(screen.getByText("alive")).toBeInTheDocument();
  });

  it("summarises the sites above the table", async () => {
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json([
          makeSite({ id: 1, name: "one" }),
          makeSite({ id: 2, name: "two", status: "lapsed" }),
        ]),
      ),
    );

    render(<Sites />);

    expect(await screen.findByText("2 sites · 1 alive · 1 lapsed")).toBeInTheDocument();
  });

  it("invites the first site when there are none", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([])));

    render(<Sites />);

    expect(
      await screen.findByText("No sites yet. Add the first site you want to keep alive."),
    ).toBeInTheDocument();
  });

  it("says so when the sites cannot be loaded", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));

    render(<Sites />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Sites could not be loaded");
  });

  it("shows the stored session's details when a row is expanded", async () => {
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Show details for example" }));

    expect(await screen.findByText(/2 cookie\(s\), captured/)).toBeInTheDocument();
    expect(screen.getByText("https://example.org/home")).toBeInTheDocument();
  });

  it("says a site has no session yet", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ session: null })])));
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Show details for example" }));

    expect(await screen.findByText("none — log in to capture one")).toBeInTheDocument();
  });

  it("checks a site on demand and reloads the list", async () => {
    let checks = 0;
    server.use(
      http.post("/api/sites/1/check", () => {
        checks += 1;
        return HttpResponse.json({
          id: 1,
          site_id: 1,
          started_at: "2026-09-06T12:00:00Z",
          outcome: "ok",
          status_code: 200,
          final_url: null,
          duration_ms: 12,
          detail: null,
        });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Check now" }));

    await waitFor(() => expect(checks).toBe(1));
  });

  it("adds a site", async () => {
    const created: unknown[] = [];
    server.use(
      http.post("/api/sites", async ({ request }) => {
        created.push(await request.json());
        return HttpResponse.json(makeSite({ name: "new site" }), { status: 201 });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));
    await userEvent.type(form.getByLabelText(/^Name/), "new site");
    await userEvent.type(form.getByLabelText(/Ping URL/), "https://new.example.org/home");
    await userEvent.click(form.getByRole("button", { name: "Add site" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]).toMatchObject({
      name: "new site",
      ping_url: "https://new.example.org/home",
    });
  });

  it("reports why a site could not be saved", async () => {
    server.use(
      http.post("/api/sites", () =>
        HttpResponse.json({ detail: "a site with that name already exists" }, { status: 409 }),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));
    await userEvent.type(form.getByLabelText(/^Name/), "example");
    await userEvent.type(form.getByLabelText(/Ping URL/), "https://example.org/home");
    await userEvent.click(form.getByRole("button", { name: "Add site" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });

  it("sends empty pattern fields as nothing rather than as an empty pattern", async () => {
    // An empty string is a pattern that matches everything, which would make every check pass.
    const created: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/sites", async ({ request }) => {
        created.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeSite(), { status: 201 });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));
    await userEvent.type(form.getByLabelText(/^Name/), "bare");
    await userEvent.type(form.getByLabelText(/Ping URL/), "https://bare.example.org/");
    await userEvent.click(form.getByRole("button", { name: "Add site" }));

    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]!.success_pattern).toBeNull();
    expect(created[0]!.login_url_pattern).toBeNull();
  });

  it("prefills the form when editing, and keeps the site's own values", async () => {
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Edit example" }));

    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByLabelText(/^Name/)).toHaveValue("example");
    expect(dialog.getByLabelText(/Login page looks like/)).toHaveValue("login.php");
  });

  it("asks before deleting a site", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    let deleted = 0;
    server.use(
      http.delete("/api/sites/1", () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Delete example" }));

    expect(confirm).toHaveBeenCalled();
    expect(deleted).toBe(0);
    confirm.mockRestore();
  });

  it("deletes a site once confirmed", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    let deleted = 0;
    server.use(
      http.delete("/api/sites/1", () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Delete example" }));

    await waitFor(() => expect(deleted).toBe(1));
    confirm.mockRestore();
  });

  it("closes the form without saving", async () => {
    let posted = 0;
    server.use(
      http.post("/api/sites", () => {
        posted += 1;
        return HttpResponse.json(makeSite(), { status: 201 });
      }),
    );
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));

    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posted).toBe(0);
  });

  it("reloads the list after a session is captured", async () => {
    let listings = 0;
    server.use(
      http.get("/api/sites", () => {
        listings += 1;
        return HttpResponse.json([makeSite()]);
      }),
      http.post("/api/sites/1/session/import", () => HttpResponse.json({ detail: "imported" })),
    );
    render(<Sites />);
    await screen.findByText("example");
    const before = listings;

    await userEvent.click(screen.getByRole("button", { name: "Log in to example" }));
    await userEvent.click(screen.getByRole("button", { name: "Paste cookies" }));
    await userEvent.type(screen.getByLabelText("Cookies"), "uid=1");
    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    await waitFor(() => expect(listings).toBeGreaterThan(before));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the site's own icon when it has one", async () => {
    const favicon = "data:image/svg+xml;base64,PHN2Zy8+";
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ favicon })])));

    render(<Sites />);
    await screen.findByText("example");

    expect(screen.getByRole("presentation", { hidden: true })).toHaveAttribute("src", favicon);
  });

  it("shows a malformed ping URL as it is rather than blanking the cell", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ ping_url: "not-a-url" })])));

    render(<Sites />);

    expect(await screen.findByText("not-a-url")).toBeInTheDocument();
  });

  it("shows a site's notes when there are any", async () => {
    server.use(
      http.get("/api/sites", () => HttpResponse.json([makeSite({ notes: "second account" })])),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Show details for example" }));

    expect(await screen.findByText("second account")).toBeInTheDocument();
  });

  it("dims a site that is not being checked", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ enabled: false })])));

    render(<Sites />);
    await screen.findByText("example");

    expect(screen.getByText("example").closest("tr")).toHaveClass("opacity-60");
  });
});

describe("the site form's examples", () => {
  it("labels the pattern examples as examples", async () => {
    // "Enter your password" as a bare placeholder reads as an instruction to type one — in a form
    // where a password field would be entirely plausible.
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));

    for (const label of [/Login page looks like/, /Page must contain/, /Page must not contain/]) {
      expect(form.getByLabelText(label)).toHaveAttribute(
        "placeholder",
        expect.stringMatching(/^e\.g\. /),
      );
    }
  });

  it("keeps a browser from autofilling a password into a pattern field", async () => {
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));

    expect(form.getByLabelText(/Page must not contain/)).toHaveAttribute("autocomplete", "off");
  });
});
