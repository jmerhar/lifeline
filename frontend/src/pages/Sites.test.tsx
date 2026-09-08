/** The main screen: what it shows, and what the buttons do. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { Sites } from "./Sites";
import { makeSite } from "../test/factories";
import { render } from "../test/render";
import { server } from "../test/server";

/** Fill in the add form's two required fields. */
async function fillTheSite(form: ReturnType<typeof within>, name: string, url: string) {
  await userEvent.type(form.getByLabelText(/^Name/), name);
  await userEvent.type(form.getByLabelText(/Ping URL/), url);
}

/** Open an existing site's editor on one of its tabs. */
async function openTab(label: RegExp) {
  await userEvent.click(screen.getByRole("button", { name: "Edit example" }));
  const form = within(screen.getByRole("dialog"));
  await userEvent.click(form.getByRole("tab", { name: label }));
  return form;
}

describe("Sites", () => {
  it("lists a site with its state and host", async () => {
    render(<Sites />);

    expect(await screen.findByText("example")).toBeInTheDocument();
    expect(screen.getByText("example.org")).toBeInTheDocument();
    expect(screen.getByText("alive")).toBeInTheDocument();
  });

  it("says why a site needs attention", async () => {
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json([
          makeSite({
            status: "at_risk",
            risk: "the account lapses in 4 day(s), before the next check on 16 Sep 2026",
          }),
        ]),
      ),
    );

    render(<Sites />);

    expect(await screen.findByText(/the account lapses in 4 day\(s\)/)).toBeInTheDocument();
  });

  it("does not invent a reason for a healthy site", async () => {
    render(<Sites />);
    await screen.findByText("alive");

    // Asserted on the cell's structure, not on absent text: an empty reason element renders
    // nothing a text query can look for, so a query alone would pass however the row is built.
    // Third cell: the switch, the site, then the status.
    const status = document.querySelectorAll("tbody tr td")[2]!;
    expect(status.children).toHaveLength(1);
    expect(screen.queryByText(/before the next check/)).not.toBeInTheDocument();
  });

  it("puts the reason beside the status, not somewhere else", async () => {
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json([makeSite({ status: "at_risk", risk: "the account lapses in 4 day(s)" })]),
      ),
    );

    render(<Sites />);
    await screen.findByText("due soon");

    // Third cell: the switch, the site, then the status.
    const status = document.querySelectorAll("tbody tr td")[2]!;
    expect(status.children).toHaveLength(2);
    expect(status.textContent).toContain("the account lapses in 4 day(s)");
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
    // The rendered expiry, not just the field name: the name alone is already guarded by tsc.
    expect(screen.getByText(/1 Jan 2027/)).toBeInTheDocument();
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
    await fillTheSite(form, "new site", "https://new.example.org/home");
    await userEvent.click(form.getByRole("button", { name: "Add site and log in" }));

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
    await fillTheSite(form, "example", "https://example.org/home");
    await userEvent.click(form.getByRole("button", { name: "Add site and log in" }));

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
    await fillTheSite(form, "bare", "https://bare.example.org/");
    await userEvent.click(form.getByRole("button", { name: "Add site and log in" }));

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

    await userEvent.click(dialog.getByRole("tab", { name: /Spotting a dead session/ }));

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
      // The panel asks for a browser as it opens, before this test takes the paste route
      // instead. Left unhandled it is a real request escaping the test.
      http.post("/api/sites/1/login-session", () =>
        HttpResponse.json({ detail: "browser sessions are disabled" }, { status: 503 }),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    const before = listings;

    await userEvent.click(screen.getByRole("button", { name: "Log in to example" }));
    await userEvent.click(screen.getByRole("button", { name: "Paste cookies" }));
    await userEvent.type(screen.getByLabelText("Cookies"), "uid=1");
    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    await waitFor(() => expect(listings).toBeGreaterThan(before));
    // The login hands straight over to the panel it has just made answerable, rather than
    // leaving someone on the list wondering what to do next.
    expect(await screen.findByRole("tab", { name: /Spotting a dead session/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
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
    // A bare placeholder reads as an instruction, in a form where a credential field would be
    // entirely plausible.
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    for (const label of [/Login page looks like/, /Page must contain/, /Page must not contain/]) {
      expect(form.getByLabelText(label)).toHaveAttribute(
        "placeholder",
        expect.stringMatching(/^e\.g\. /),
      );
    }
  });

  it("names no password in any example", async () => {
    // A placeholder mentioning one gets the field classified as a credential, which makes a
    // password manager fill it in and then offer to save a login for the whole form.
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    for (const field of form.getAllByRole("textbox")) {
      expect(field.getAttribute("placeholder") ?? "").not.toMatch(/password/i);
    }
  });

  it("tells every password manager to leave the pattern fields alone", async () => {
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    const field = form.getByLabelText(/Page must not contain/);
    expect(field).toHaveAttribute("autocomplete", "off");
    // One attribute per vendor, none of which the others honour.
    expect(field).toHaveAttribute("data-bwignore");
    expect(field).toHaveAttribute("data-1p-ignore");
    expect(field).toHaveAttribute("data-lpignore", "true");
    expect(field).toHaveAttribute("data-form-type", "other");
  });
});

describe("adding a site", () => {
  it("asks only what the site is, and nothing it cannot answer yet", async () => {
    // The detection question needs a page seen both signed in and signed out. Asking it here
    // offered a disabled option and three fields nobody could fill.
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));

    expect(form.getByLabelText(/^Name/)).toBeInTheDocument();
    expect(form.queryByLabelText(/Login page looks like/)).not.toBeInTheDocument();
    expect(form.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("can be saved with nothing but a name and a URL", async () => {
    // Never blocked: there is no rule to give yet, and a form that will not submit is the bug
    // this replaced.
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));
    await fillTheSite(form, "minimal", "https://example.org/home");

    expect(form.getByRole("button", { name: "Add site and log in" })).toBeEnabled();
  });

  it("keeps notes with the rest of the site, not filed under rarely needed", async () => {
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));

    expect(form.getByLabelText(/^Notes/)).toBeInTheDocument();
  });

  it("opens the login as soon as the site exists", async () => {
    server.use(
      http.post("/api/sites", () => HttpResponse.json(makeSite({ name: "fresh" }), { status: 201 })),
      http.post("/api/sites/1/login-session", () =>
        HttpResponse.json({ detail: "browser sessions are disabled" }, { status: 503 }),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: /Add site/ }));
    const form = within(screen.getByRole("dialog"));
    await fillTheSite(form, "fresh", "https://example.org/home");

    await userEvent.click(form.getByRole("button", { name: "Add site and log in" }));

    expect(await screen.findByText(/Log in to fresh/)).toBeInTheDocument();
  });

  it("does not open a login when an edit is saved", async () => {
    server.use(http.put("/api/sites/1", () => HttpResponse.json(makeSite())));
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: "Edit example" }));
    const form = within(screen.getByRole("dialog"));

    await userEvent.click(form.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.queryByText(/Log in to example/)).not.toBeInTheDocument();
  });
});

describe("editing a site", () => {
  it("offers its settings as tabs rather than as a sequence", async () => {
    // Nothing has to be walked past to reach the one thing someone came to change.
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Edit example" }));
    const form = within(screen.getByRole("dialog"));

    expect(form.getAllByRole("tab")).toHaveLength(3);
    expect(form.queryByRole("button", { name: "Next" })).not.toBeInTheDocument();
  });

  it("keeps what was typed on one tab while another is open", async () => {
    render(<Sites />);
    await screen.findByText("example");
    await userEvent.click(screen.getByRole("button", { name: "Edit example" }));
    const form = within(screen.getByRole("dialog"));
    await userEvent.clear(form.getByLabelText(/^Name/));
    await userEvent.type(form.getByLabelText(/^Name/), "renamed");

    await userEvent.click(form.getByRole("tab", { name: /Advanced/ }));
    await userEvent.click(form.getByRole("tab", { name: /The site/ }));

    expect(form.getByLabelText(/^Name/)).toHaveValue("renamed");
  });

  it("refuses to save a site that could not tell a dead session apart", async () => {
    // Individually optional, collectively load-bearing: with none of them set a check reports
    // only that the site answered. Saying so beats saving something that notices nothing.
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json([
          makeSite({ login_url_pattern: null, success_pattern: null, failure_pattern: null }),
        ]),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    await userEvent.click(form.getByRole("radio", { name: /Set them myself/ }));

    expect(form.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(form.getByText(/could not tell a dead session/)).toBeInTheDocument();
  });

  it("allows it once a rule is given", async () => {
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);
    await userEvent.clear(form.getByLabelText(/Login page looks like/));

    await userEvent.type(form.getByLabelText(/Page must contain/), "Log out");

    expect(form.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("allows it when not detecting is chosen deliberately", async () => {
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    await userEvent.click(form.getByRole("radio", { name: /Don't detect/ }));

    expect(form.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("cannot offer to work it out for a site with no session", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ session: null })])));
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    expect(form.getByRole("radio", { name: /Work it out/ })).toBeDisabled();
    expect(form.getByText(/Log in to this site first/)).toBeInTheDocument();
  });

  it("starts on the comparison for a site whose login was just captured", async () => {
    // No rules but a session means the login has just been taken, which is when the comparison
    // is both possible and the reason someone is looking at this panel.
    server.use(
      http.get("/api/sites", () =>
        HttpResponse.json([
          makeSite({ login_url_pattern: null, success_pattern: null, failure_pattern: null }),
        ]),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    expect(form.getByRole("radio", { name: /Work it out/ })).toBeChecked();
  });

  it("fills the rules in from a comparison, and says what it found", async () => {
    server.use(
      // Every field differs from what the site already holds, so a rule that was not applied
      // shows up as the old value rather than as a coincidence.
      http.get("/api/sites", () =>
        HttpResponse.json([
          makeSite({
            login_url_pattern: "stale.php",
            success_pattern: "Stale text",
            failure_pattern: "Stale failure",
          }),
        ]),
      ),
      http.post("/api/sites/1/detect", () =>
        HttpResponse.json({
          login_url_pattern: "login.php",
          success_pattern: "Log out",
          failure_pattern: null,
          notes: ["Signed out, the request ends at https://example.org/login.php instead."],
        }),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    await userEvent.click(form.getByRole("radio", { name: /Work it out/ }));
    await userEvent.click(form.getByRole("button", { name: "Compare the two" }));

    expect(await form.findByText(/ends at https:\/\/example\.org\/login\.php/)).toBeInTheDocument();
    // Every rule it found, not just one: each is applied by its own line, and a line that was
    // dropped would leave that field holding whatever the site already had.
    expect(form.getByLabelText(/Login page looks like/)).toHaveValue("login.php");
    expect(form.getByLabelText(/Page must contain/)).toHaveValue("Log out");
    expect(form.getByLabelText(/Page must not contain/)).toHaveValue("");
  });

  it("reports a comparison that could not be made", async () => {
    server.use(
      http.post("/api/sites/1/detect", () =>
        HttpResponse.json({ detail: "could not reach the site" }, { status: 502 }),
      ),
    );
    render(<Sites />);
    await screen.findByText("example");
    const form = await openTab(/Spotting a dead session/);

    await userEvent.click(form.getByRole("radio", { name: /Work it out/ }));
    await userEvent.click(form.getByRole("button", { name: "Compare the two" }));

    expect(await form.findByRole("alert")).toHaveTextContent("could not reach the site");
  });
});

describe("pausing a site from the list", () => {
  it("switches a site off without opening a form", async () => {
    const sent: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/sites/1", async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeSite({ enabled: false }));
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("switch", { name: "Pause example" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.enabled).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("switches a paused site back on", async () => {
    const sent: Array<Record<string, unknown>> = [];
    server.use(
      http.get("/api/sites", () => HttpResponse.json([makeSite({ enabled: false })])),
      http.put("/api/sites/1", async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeSite());
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("switch", { name: "Resume example" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.enabled).toBe(true);
  });

  it("says so when a site could not be paused", async () => {
    server.use(
      http.put("/api/sites/1", () => HttpResponse.json({ detail: "nope" }, { status: 500 })),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("switch", { name: "Pause example" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be paused");
  });

  it("keeps the rest of the site's settings when only pausing it", async () => {
    // Sent as a whole site, so a field left out here would be silently reset.
    const sent: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/sites/1", async ({ request }) => {
        sent.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeSite({ enabled: false }));
      }),
    );
    render(<Sites />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("switch", { name: "Pause example" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({
      name: "example",
      ping_url: "https://example.org/home",
      login_url_pattern: "login.php",
      interval_days: 7,
    });
  });

  it("reflects the state a site is already in", async () => {
    server.use(http.get("/api/sites", () => HttpResponse.json([makeSite({ enabled: false })])));
    render(<Sites />);
    await screen.findByText("example");

    expect(screen.getByRole("switch", { name: "Resume example" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});
