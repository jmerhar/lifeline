/** The settings screen. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { Settings } from "./Settings";
import { makeSettings } from "../test/factories";
import { render } from "../test/render";
import { server } from "../test/server";

describe("Settings", () => {
  it("shows the current values", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ apprise_urls: "tgram://token/chat", retention_days: 30 })),
      ),
    );

    render(<Settings />);

    expect(await screen.findByDisplayValue("tgram://token/chat")).toBeInTheDocument();
    expect(screen.getByLabelText("Keep history for")).toHaveValue(30);
  });

  it("puts notifications first, because nothing else matters if they are unset", async () => {
    render(<Settings />);

    const headings = await screen.findAllByRole("heading");
    expect(headings[0]).toHaveTextContent("Notifications");
  });

  it("saves a change", async () => {
    const saved: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/settings", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        saved.push(body);
        return HttpResponse.json(body);
      }),
    );
    render(<Settings />);
    await screen.findByLabelText("Where to send them");

    await userEvent.type(screen.getByLabelText("Where to send them"), "ntfy://host/topic");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]!.apprise_urls).toBe("ntfy://host/topic");
  });

  it("confirms that the settings were saved", async () => {
    server.use(http.put("/api/settings", () => HttpResponse.json(makeSettings())));
    render(<Settings />);
    await screen.findByLabelText("Where to send them");

    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Settings saved.");
  });

  it("turns an event off", async () => {
    const saved: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/settings", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        saved.push(body);
        return HttpResponse.json(body);
      }),
    );
    render(<Settings />);
    await screen.findByLabelText("A session started working again");

    await userEvent.click(screen.getByLabelText("A session started working again"));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]!.notify_on_recovered).toBe(false);
  });

  it("sends a test notification and reports what happened", async () => {
    server.use(
      http.post("/api/settings/test-notification", () =>
        HttpResponse.json({ detail: "test notification sent" }),
      ),
    );
    render(<Settings />);
    await screen.findByLabelText("Where to send them");

    await userEvent.click(screen.getByRole("button", { name: "Send a test notification" }));

    expect(await screen.findByRole("status")).toHaveTextContent("test notification sent");
  });

  it("passes on the reason nothing was sent", async () => {
    // A silent success would leave a typo in the settings undiscovered until it mattered.
    server.use(
      http.post("/api/settings/test-notification", () =>
        HttpResponse.json({ detail: "nothing was sent: check that at least one destination…" }),
      ),
    );
    render(<Settings />);
    await screen.findByLabelText("Where to send them");

    await userEvent.click(screen.getByRole("button", { name: "Send a test notification" }));

    expect(await screen.findByRole("status")).toHaveTextContent("nothing was sent");
  });

  it("reports settings that could not be saved", async () => {
    server.use(
      http.put("/api/settings", () => HttpResponse.json({ detail: "nope" }, { status: 422 })),
    );
    render(<Settings />);
    await screen.findByLabelText("Where to send them");

    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("says so when the settings cannot be loaded", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json({ detail: "boom" }, { status: 500 })),
    );

    render(<Settings />);

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
  });
});

describe("the log level", () => {
  it("saves a change", async () => {
    const saved: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/settings", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        saved.push(body);
        return HttpResponse.json(body);
      }),
    );
    render(<Settings />);
    await screen.findByLabelText("Log detail");

    await userEvent.selectOptions(screen.getByLabelText("Log detail"), "DEBUG");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]!.log_level).toBe("DEBUG");
  });

  it("says that a change applies at once, and where the log goes", async () => {
    // The reason to raise it is to watch something happening now, so it would be no use if it
    // needed a restart — and a log nobody can find is no use either.
    render(<Settings />);

    const hint = await screen.findByText(/Takes effect at once/);
    expect(hint).toHaveTextContent("logs/lifeline.log");
  });

  it("describes info as covering every check, not just debug", async () => {
    // The first wording put checks at debug level, which was both wrong and a description of a
    // gap: the application logged nothing of its own per check.
    render(<Settings />);
    await screen.findByLabelText("Log detail");

    expect(screen.getByRole("option", { name: /^Info/ })).toHaveTextContent("every request, check");
    expect(screen.getByRole("option", { name: /^Debug/ })).toHaveTextContent("why each check");
  });
})

describe("the language a site is asked to answer in", () => {
  it("saves the header for the language that was picked", async () => {
    // A site serving more than one decides from this, and a pattern typed from a page in one
    // language matches nothing in another.
    const sent: Array<Record<string, unknown>> = [];
    server.use(
      http.put("/api/settings", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        sent.push(body);
        return HttpResponse.json(body);
      }),
    );
    render(<Settings />);
    const field = await screen.findByLabelText(/Answer in this language/);

    await userEvent.selectOptions(field, "Hungarian");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    // Picking a language sends the header for it, which is what a check asks with. A language
    // offered without a country has nothing to fall back to, so the header is the tag itself.
    expect(sent[0]!.accept_language).toBe("hu");
  });

  it("shows what is configured", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ accept_language: "de-DE,de;q=0.9" })),
      ),
    );
    render(<Settings />);

    expect(await screen.findByLabelText(/Answer in this language/)).toHaveValue("de-DE");
    // The header is the language's own, so there is nothing to write by hand.
    expect(screen.queryByLabelText("Accept-Language header")).not.toBeInTheDocument();
  });

  it("offers the header itself for a language it does not list", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ accept_language: "de-AT,de;q=0.8,en;q=0.5" })),
      ),
    );
    render(<Settings />);

    expect(await screen.findByLabelText(/Answer in this language/)).toHaveValue("own");
    expect(screen.getByLabelText("Accept-Language header")).toHaveValue("de-AT,de;q=0.8,en;q=0.5");
  });

  it("keeps a hand-written header exactly as it is typed", async () => {
    const sent: Record<string, unknown>[] = [];
    server.use(
      http.put("/api/settings", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        sent.push(body);
        return HttpResponse.json(body);
      }),
    );
    render(<Settings />);

    await userEvent.selectOptions(
      await screen.findByLabelText(/Answer in this language/),
      screen.getByRole("option", { name: /Something else/ }),
    );
    const header = screen.getByLabelText("Accept-Language header");
    await userEvent.clear(header);
    await userEvent.type(header, "sl-SI,sl;q=0.9,en;q=0.5");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]!.accept_language).toBe("sl-SI,sl;q=0.9,en;q=0.5");
  });

  it("keeps the box open while a typed header happens to match a listed language", async () => {
    render(<Settings />);

    await userEvent.selectOptions(
      await screen.findByLabelText(/Answer in this language/),
      screen.getByRole("option", { name: /Something else/ }),
    );
    const header = screen.getByLabelText("Accept-Language header");
    await userEvent.clear(header);
    // Exactly the header German is offered as: the field must not decide it knows better and
    // take the box away mid-sentence.
    await userEvent.type(header, "de-DE,de;q=0.9");

    expect(screen.getByLabelText("Accept-Language header")).toHaveValue("de-DE,de;q=0.9");
  });
});
