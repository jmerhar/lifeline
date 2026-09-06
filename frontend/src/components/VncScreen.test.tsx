/** The streamed browser panel. */

import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const constructed: Array<{ url: string; scaleViewport: boolean; clipViewport: boolean }> = [];
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

describe("VncScreen", () => {
  beforeEach(() => {
    constructed.length = 0;
    listeners.clear();
    disconnect.mockClear();
  });

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
