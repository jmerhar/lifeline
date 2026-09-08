/**
 * The live browser, streamed into the page.
 *
 * noVNC talks RFB over a websocket; the API bridges that to the x11vnc server running beside the
 * browser inside the container. The websocket URL is built from the current origin so this works
 * through a reverse proxy without being told where it lives.
 */

import RFB from "@novnc/novnc";
import { useCallback, useEffect, useRef, useState } from "react";

export interface VncHandle {
  /** Put text on the remote clipboard and paste it into whatever has focus there. */
  paste: (text: string) => void;
}

export function VncScreen({
  path,
  onReady,
  onDisconnected,
  className = "",
}: {
  path: string;
  onReady?: (handle: VncHandle) => void;
  onDisconnected?: (clean: boolean) => void;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const connection = useRef<RFB | null>(null);
  const [failed, setFailed] = useState(false);

  const paste = useCallback((text: string) => {
    const rfb = connection.current;
    if (!rfb || !text) return;
    // Two steps, in this order. The clipboard message carries the text to the remote X server;
    // the keystrokes then paste it into the focused field. Sending the keystrokes without the
    // clipboard would paste whatever the remote had before, which is nothing.
    rfb.clipboardPasteFrom(text);
    for (const [keysym, code] of PASTE_CHORD) {
      rfb.sendKey(keysym, code, true);
    }
    for (const [keysym, code] of [...PASTE_CHORD].reverse()) {
      rfb.sendKey(keysym, code, false);
    }
  }, []);

  useEffect(() => {
    const element = container.current;
    if (!element) return;

    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const rfb = new RFB(element, `${scheme}//${window.location.host}${path}`, {});
    connection.current = rfb;
    // Scaled rather than clipped: the browser inside runs at a fixed size, and a panel narrower
    // than that would otherwise hide the half of the login form it cannot fit.
    rfb.scaleViewport = true;
    rfb.clipViewport = false;

    const handleDisconnect = (event: CustomEvent<{ clean: boolean }>) => {
      if (!event.detail?.clean) setFailed(true);
      onDisconnected?.(Boolean(event.detail?.clean));
    };
    rfb.addEventListener("disconnect", handleDisconnect as EventListener);
    onReady?.({ paste });

    return () => {
      rfb.removeEventListener("disconnect", handleDisconnect as EventListener);
      connection.current = null;
      try {
        rfb.disconnect();
      } catch {
        // Already gone; there is nothing to disconnect from.
      }
    };
  }, [path, onDisconnected, onReady, paste]);

  return (
    <div className={`relative ${className}`}>
      <div ref={container} className="h-full w-full bg-black" data-testid="vnc-screen" />
      {failed ? (
        <p
          role="alert"
          className="absolute inset-x-0 bottom-0 bg-lapsed/90 px-3 py-2 text-small text-white"
        >
          The connection to the browser dropped. Close this panel and start again.
        </p>
      ) : null}
    </div>
  );
}

/**
 * Control+V, as X keysyms.
 *
 * The remote browser is Chromium on Linux, so Control rather than Command whatever the machine
 * looking at it happens to be.
 */
const PASTE_CHORD: ReadonlyArray<[number, string]> = [
  [0xffe3, "ControlLeft"],
  [0x76, "KeyV"],
];
