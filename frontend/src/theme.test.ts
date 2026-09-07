/**
 * The theme's own invariants.
 *
 * A colour and a font size sharing a name is not a style question, it is a bug: Tailwind gives
 * both `text-<name>`, emits both declarations for it, and the colour wins. A colour named "base"
 * therefore made `text-base` set the body font size *and* paint the text the page's background
 * colour — so every element without an explicit colour was invisible, in both themes. Nothing in
 * a jsdom test can see that, because the CSS is never computed there; this asserts the shape of
 * the config instead.
 */

import { describe, expect, it } from "vitest";

// @ts-expect-error - a JS config with no types of its own
import config from "../tailwind.config.js";

const theme = config.theme.extend as {
  colors: Record<string, string>;
  fontSize: Record<string, unknown>;
};

describe("theme tokens", () => {
  it("gives no colour the same name as a font size", () => {
    const clashes = Object.keys(theme.colors).filter((name) => name in theme.fontSize);

    expect(clashes).toEqual([]);
  });

  it("defines every colour through a custom property, so the themes can swap them", () => {
    for (const [name, value] of Object.entries(theme.colors)) {
      expect(value, name).toMatch(/^rgb\(var\(--[a-z-]+\) \/ <alpha-value>\)$/);
    }
  });
});
