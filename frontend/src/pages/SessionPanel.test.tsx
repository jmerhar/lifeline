/** Giving a site a session, both ways. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useEffect } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionPanel } from "./SessionPanel";
import { makeSite } from "../test/factories";
import { render } from "../test/render";
import { server } from "../test/server";

// noVNC opens a real websocket and paints a canvas, neither of which exists here. The screen
// component is stubbed so these tests are about the panel's own behaviour: starting a
// session, saving it, and shutting it down when the panel closes.
const pastedToRemote: string[] = [];

vi.mock("../components/VncScreen", () => ({
  VncScreen: ({
    path,
    onReady,
  }: {
    path: string;
    onReady?: (handle: { paste: (text: string) => void }) => void;
  }) => {
    // In an effect, exactly as the real component does it. Calling it during render hands the
    // parent a new object on every pass, so its setState re-renders this, which calls it again —
    // an infinite loop that hangs the test run rather than failing it.
    useEffect(() => {
      onReady?.({ paste: (text: string) => pastedToRemote.push(text) });
    }, [onReady]);
    return <div data-testid="vnc-screen" data-path={path} />;
  },
}));

const site = makeSite();

const opened = {
  site_id: 1,
  ws_path: "/api/browser/token-abc/ws",
  width: 1280,
  height: 800,
  expires_at: "2026-09-06T13:00:00Z",
};

beforeEach(() => {
  pastedToRemote.length = 0;
});

describe("SessionPanel", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/sites/1/login-session", () => HttpResponse.json(opened)),
      http.post("/api/browser/token-abc/save", () => HttpResponse.json({ detail: "session saved" })),
      http.delete("/api/browser/token-abc", () =>
        HttpResponse.json({ detail: "login session closed" }),
      ),
    );
  });

  it("starts a browser and streams it", async () => {
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    const screenEl = await screen.findByTestId("vnc-screen");
    expect(screenEl).toHaveAttribute("data-path", "/api/browser/token-abc/ws");
  });

  it("explains that two-factor prompts work", async () => {
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    expect(await screen.findByText(/Two-factor prompts and bot checks/)).toBeInTheDocument();
  });

  it("saves the session the browser is holding", async () => {
    const onSaved = vi.fn();
    render(<SessionPanel site={site} onClose={() => {}} onSaved={onSaved} />);
    await screen.findByTestId("vnc-screen");

    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("shuts the browser down when the panel closes unsaved", async () => {
    // A headful browser left running holds an X server until its idle timeout expires.
    let closed = 0;
    server.use(
      http.delete("/api/browser/token-abc", () => {
        closed += 1;
        return HttpResponse.json({ detail: "closed" });
      }),
    );
    const { unmount } = render(
      <SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />,
    );
    await screen.findByTestId("vnc-screen");

    unmount();

    await waitFor(() => expect(closed).toBe(1));
  });

  it("says so when no browser is available", async () => {
    server.use(
      http.post("/api/sites/1/login-session", () =>
        HttpResponse.json(
          { detail: "browser sessions are disabled in this deployment" },
          { status: 503 },
        ),
      ),
    );

    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("disabled in this deployment");
  });

  it("reports a session that could not be saved", async () => {
    server.use(
      http.post("/api/browser/token-abc/save", () =>
        HttpResponse.json({ detail: "that login session is not open" }, { status: 404 }),
      ),
    );
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);
    await screen.findByTestId("vnc-screen");

    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not open");
  });

  it("imports pasted cookies", async () => {
    const imported: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/sites/1/session/import", async ({ request }) => {
        imported.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ detail: "session imported" });
      }),
    );
    const onSaved = vi.fn();
    render(<SessionPanel site={site} onClose={() => {}} onSaved={onSaved} />);

    await userEvent.click(screen.getByRole("button", { name: "Paste cookies" }));
    await userEvent.type(screen.getByLabelText("Cookies"), "uid=1; pass=2");
    await userEvent.type(screen.getByLabelText("User-Agent"), "Pasted/1.0");
    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(imported[0]).toEqual({ text: "uid=1; pass=2", user_agent: "Pasted/1.0" });
  });

  it("sends no user agent when the field is left empty", async () => {
    const imported: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/sites/1/session/import", async ({ request }) => {
        imported.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ detail: "session imported" });
      }),
    );
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: "Paste cookies" }));
    await userEvent.type(screen.getByLabelText("Cookies"), "uid=1");
    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    await waitFor(() => expect(imported).toHaveLength(1));
    expect(imported[0]!.user_agent).toBeNull();
  });

  it("reports cookies it cannot read", async () => {
    server.use(
      http.post("/api/sites/1/session/import", () =>
        HttpResponse.json({ detail: "'prose' is not a name=value pair" }, { status: 422 }),
      ),
    );
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: "Paste cookies" }));
    await userEvent.type(screen.getByLabelText("Cookies"), "prose");
    await userEvent.click(screen.getByRole("button", { name: "Save session" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("not a name=value pair");
  });
});

describe("sending a password to the remote browser", () => {
  beforeEach(() => {
    server.use(
      http.post("/api/sites/1/login-session", () => HttpResponse.json(opened)),
      http.delete("/api/browser/token-abc", () => HttpResponse.json({ detail: "closed" })),
    );
  });

  it("offers a field for it", async () => {
    // A password manager on this machine cannot fill a browser running on another one, and an
    // ordinary paste does not cross that gap.
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    expect(await screen.findByLabelText("Send to the browser")).toBeInTheDocument();
  });

  it("masks what is typed there", async () => {
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);

    expect(await screen.findByLabelText("Send to the browser")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("sends it to the browser and keeps nothing", async () => {
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);
    const field = await screen.findByLabelText("Send to the browser");

    await userEvent.type(field, "a-difficult-password");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(pastedToRemote).toEqual(["a-difficult-password"]);
    // Cleared, so it is not left sitting in the page after it has been sent.
    expect(field).toHaveValue("");
    expect(await screen.findByRole("status")).toHaveTextContent("Sent");
  });

  it("will not send nothing", async () => {
    render(<SessionPanel site={site} onClose={() => {}} onSaved={() => {}} />);
    await screen.findByLabelText("Send to the browser");

    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});
