import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PulseStrip } from "./PulseStrip";

describe("PulseStrip", () => {
  it("draws a tick for every check, plus the empty ones", () => {
    const { container } = render(<PulseStrip pulse={[{ outcome: "ok" }, { outcome: "ok" }]} />);

    // Twelve slots always, so rows line up down the column whatever their history.
    expect(container.querySelectorAll("rect")).toHaveLength(12);
  });

  it("deflects a failure downwards and a success upwards", () => {
    // Direction, not just colour: the strip has to be readable in grey and to a colourblind
    // reader, and it is the fastest way to see that something has been failing for a while.
    const { container } = render(
      <PulseStrip pulse={[{ outcome: "ok" }, { outcome: "login_expired" }]} />,
    );
    const ticks = [...container.querySelectorAll("rect")].slice(-2);

    const [good, bad] = ticks.map((tick) => Number(tick.getAttribute("y")));
    expect(good).toBeLessThan(bad!);
  });

  it("puts the newest check at the right-hand edge", () => {
    const { container } = render(
      <PulseStrip pulse={[{ outcome: "ok" }, { outcome: "http_error" }]} />,
    );
    const ticks = [...container.querySelectorAll("rect")];
    const last = ticks.at(-1)!;
    const secondToLast = ticks.at(-2)!;

    expect(Number(last.getAttribute("x"))).toBeGreaterThan(Number(secondToLast.getAttribute("x")));
    // The most recent outcome was a failure, so the right-most tick hangs below the baseline.
    expect(Number(last.getAttribute("y"))).toBeGreaterThan(
      Number(secondToLast.getAttribute("y")),
    );
  });

  it("describes itself for a screen reader", () => {
    render(<PulseStrip pulse={[{ outcome: "ok" }, { outcome: "login_expired" }]} />);

    expect(screen.getByRole("img")).toHaveAccessibleName("2 recent checks, 1 failed");
  });

  it("says when everything is fine", () => {
    render(<PulseStrip pulse={[{ outcome: "ok" }]} />);

    expect(screen.getByRole("img")).toHaveAccessibleName("1 recent check, all ok");
  });

  it("says when there is nothing yet", () => {
    render(<PulseStrip pulse={[]} />);

    expect(screen.getByRole("img")).toHaveAccessibleName("No checks yet");
  });

  it("titles each tick with what it was", () => {
    const { container } = render(<PulseStrip pulse={[{ outcome: "login_expired", at: "2 Sep" }]} />);

    expect(container.querySelector("title")?.textContent).toBe("session expired · 2 Sep");
  });

  it("keeps only the last twelve checks", () => {
    const pulse = Array.from({ length: 20 }, () => ({ outcome: "ok" as const }));

    const { container } = render(<PulseStrip pulse={pulse} />);

    expect(container.querySelectorAll("rect")).toHaveLength(12);
  });
});
