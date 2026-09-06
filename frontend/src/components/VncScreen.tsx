/**
 * The live browser, streamed into the page.
 *
 * noVNC talks RFB over a websocket; the API bridges that to the x11vnc server running
 * beside the browser inside the container. The websocket URL is built from the current
 * origin so this works through a reverse proxy without being told where it lives.
 */

import RFB from "@novnc/novnc";
import { useEffect, useRef, useState } from "react";

export function VncScreen({
  path,
  onDisconnected,
  className = "",
}: {
  path: string;
  onDisconnected?: (clean: boolean) => void;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const element = container.current;
    if (!element) return;

    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    const rfb = new RFB(element, `${scheme}//${window.location.host}${path}`, {});
    // Scaled rather than clipped: the browser inside runs at a fixed size, and a panel
    // narrower than that would otherwise hide the half of the login form it cannot fit.
    rfb.scaleViewport = true;
    rfb.clipViewport = false;

    const handleDisconnect = (event: CustomEvent<{ clean: boolean }>) => {
      if (!event.detail?.clean) setFailed(true);
      onDisconnected?.(Boolean(event.detail?.clean));
    };
    rfb.addEventListener("disconnect", handleDisconnect as EventListener);

    return () => {
      rfb.removeEventListener("disconnect", handleDisconnect as EventListener);
      try {
        rfb.disconnect();
      } catch {
        // Already gone; there is nothing to disconnect from.
      }
    };
  }, [path, onDisconnected]);

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
