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

  it("says that a change applies at once", async () => {
    // The reason to raise it is to watch something happening now, so it would be no use if it
    // needed a restart.
    render(<Settings />);

    expect(await screen.findByText(/Takes effect at once/)).toBeInTheDocument();
  });
})
