/** The controls that carry state in their appearance rather than in text. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Switch } from "./ui";

/** The knob, which is the only thing inside the switch. */
function knobOf(): HTMLElement {
  return screen.getByRole("switch").firstElementChild as HTMLElement;
}

describe("Switch", () => {
  it("holds the knob at the off end when it is off", () => {
    render(<Switch checked={false} onChange={vi.fn()} label="Pause example" />);

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(knobOf().className).toContain("translate-x-0.5");
  });

  it("moves the knob to the on end when it is on", () => {
    render(<Switch checked onChange={vi.fn()} label="Pause example" />);

    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
    // Somewhere other than where the off state puts it: a switch coloured on with its knob
    // still at the off end reads as off, whatever the colour says.
    expect(knobOf().className).not.toContain("translate-x-0.5");
    expect(knobOf().className).toMatch(/translate-x-\[[\d.]+rem\]/);
  });

  it("reports the state it is being moved to", async () => {
    const onChange = vi.fn();
    render(<Switch checked onChange={onChange} label="Pause example" />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onChange).toHaveBeenCalledWith(false);
  });

  it("cannot be moved while the change it made is in flight", async () => {
    const onChange = vi.fn();
    render(<Switch checked onChange={onChange} label="Pause example" busy />);

    await userEvent.click(screen.getByRole("switch"));

    expect(onChange).not.toHaveBeenCalled();
  });
});
