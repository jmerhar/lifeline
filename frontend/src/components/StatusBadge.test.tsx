import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("names the state in words as well as colour", () => {
    // Colour alone would leave the column unreadable in grey or to a colourblind reader.
    render(<StatusBadge status="lapsed" />);

    expect(screen.getByText("lapsed")).toBeInTheDocument();
  });

  it("uses a different glyph per state", () => {
    const { container: alive } = render(<StatusBadge status="alive" />);
    const { container: risk } = render(<StatusBadge status="at_risk" />);

    expect(alive.textContent).not.toBe(risk.textContent);
  });

  it("says plainly when a site has never been checked", () => {
    render(<StatusBadge status="unknown" />);

    expect(screen.getByText("not checked")).toBeInTheDocument();
  });
});
