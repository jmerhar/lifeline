/** The streamed browser panel. */

import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const constructed: Array<{ url: string; scaleViewport: boolean; clipViewport: boolean }> = [];
const pasted: string[] = [];
const keys: Array<[number, string, boolean]> = [];
const listeners = new Map<string, EventListener>();
const disconnect = vi.fn();

vi.mock("@novnc/novnc", () => ({
  default: class FakeRfb {
    url: string;
    scaleViewport = false;
    clipViewport = true;
    constructor(_element: HTMLElement, url: string) {
      this.url = url;
      constructed.push(this);
    }
    clipboardPasteFrom(text: string) {
      pasted.push(text);
    }
    sendKey(keysym: number, code: string, down?: boolean) {
      keys.push([keysym, code, Boolean(down)]);
    }
    addEventListener(type: string, handler: EventListener) {
      listeners.set(type, handler);
    }
    removeEventListener(type: string) {
      listeners.delete(type);
    }
    disconnect = disconnect;
  },
}));

const { VncScreen } = await import("./VncScreen");

// At file level, so every describe in this file starts from a clean slate rather than only the
// first one.
beforeEach(() => {
  constructed.length = 0;
  pasted.length = 0;
  keys.length = 0;
  listeners.clear();
  disconnect.mockClear();
});

describe("VncScreen", () => {
  it("connects to the websocket path it is given, on the page's own origin", () => {
    render(<VncScreen path="/api/browser/token/ws" />);

    expect(constructed[0]!.url).toBe(`ws://${window.location.host}/api/browser/token/ws`);
  });

  it("scales the remote screen instead of cropping it", () => {
    // The browser inside runs at a fixed size; cropping would hide half the login form.
    render(<VncScreen path="/api/browser/token/ws" />);

    expect(constructed[0]!.scaleViewport).toBe(true);
  });

  it("disconnects when the panel goes away", () => {
    const { unmount } = render(<VncScreen path="/api/browser/token/ws" />);

    unmount();

    expect(disconnect).toHaveBeenCalled();
  });

  it("says so when the connection drops unexpectedly", () => {
    render(<VncScreen path="/api/browser/token/ws" />);

    // Wrapped in act because the handler sets state; without it the assertion runs before
    // React has re-rendered.
    act(() =>
      listeners.get("disconnect")?.(
        new CustomEvent("disconnect", { detail: { clean: false } }) as Event,
      ),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("connection to the browser dropped");
  });

  it("stays quiet when the connection closes cleanly", () => {
    const onDisconnected = vi.fn();
    render(<VncScreen path="/api/browser/token/ws" onDisconnected={onDisconnected} />);

    act(() =>
      listeners.get("disconnect")?.(
        new CustomEvent("disconnect", { detail: { clean: true } }) as Event,
      ),
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(onDisconnected).toHaveBeenCalledWith(true);
  });
});

describe("pasting into the remote browser", () => {
  it("hands back a paste handle once connected", () => {
    const onReady = vi.fn();

    render(<VncScreen path="/api/browser/token/ws" onReady={onReady} />);

    expect(onReady).toHaveBeenCalledWith(expect.objectContaining({ paste: expect.any(Function) }));
  });

  it("puts the text on the remote clipboard before pressing anything", () => {
    // The other order would paste whatever the remote had before, which is nothing.
    let handle: { paste: (text: string) => void } | undefined;
    render(<VncScreen path="/api/browser/token/ws" onReady={(h) => (handle = h)} />);

    handle!.paste("a-difficult-password");

    expect(pasted).toEqual(["a-difficult-password"]);
    expect(keys.length).toBeGreaterThan(0);
  });

  it("presses and releases Control and V, releasing in reverse", () => {
    let handle: { paste: (text: string) => void } | undefined;
    render(<VncScreen path="/api/browser/token/ws" onReady={(h) => (handle = h)} />);

    handle!.paste("secret");

    expect(keys.map(([, code, down]) => `${code}:${down ? "down" : "up"}`)).toEqual([
      "ControlLeft:down",
      "KeyV:down",
      "KeyV:up",
      "ControlLeft:up",
    ]);
  });

  it("does nothing with empty text", () => {
    let handle: { paste: (text: string) => void } | undefined;
    render(<VncScreen path="/api/browser/token/ws" onReady={(h) => (handle = h)} />);

    handle!.paste("");

    expect(pasted).toEqual([]);
    expect(keys).toEqual([]);
  });
});
