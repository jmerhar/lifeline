/**
 * A class Tailwind does not define is emitted as nothing, and nothing is what it then does:
 * the element renders without the spacing or the transform it names, which looks like a
 * layout that was never written rather than like a mistake. Nothing in a type check or a
 * render test sees it, because the class is in the DOM either way.
 *
 * The scale halves down to 3.5 and no further, so a `-4.5` and up is the shape that silently
 * does nothing. An exact length in brackets is always emitted and is the way to write one.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every source file the interface is built from.
 *
 * Tests are not among them: a test naming a class is describing one rather than rendering it,
 * and the examples below are the classes this looks for.
 */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

// Spacing utilities, at a half step the scale does not reach. Bracketed lengths never match:
// the digits inside them are not preceded by the hyphen this looks for.
const PHANTOM =
  /\b(?:translate-[xy]|[whmp]|[mp][xytblr]|gap|gap-[xy]|space-[xy]|inset|top|right|bottom|left|size)-(?:[4-9]|\d\d)\.5\b/g;

describe("the utility classes the interface names", () => {
  it("are all ones Tailwind defines", () => {
    const offenders = sources("src").flatMap((path) => {
      const found = readFileSync(path, "utf8").match(PHANTOM) ?? [];
      return found.map((className) => `${path}: ${className}`);
    });

    expect(offenders).toEqual([]);
  });

  it("would notice one that is not", () => {
    // The guard is only worth having if it fires, and the classes it looks for are absent by
    // the time anyone reads this — so it is pointed at one on purpose.
    expect("translate-x-4.5 ml-6.5 gap-12.5".match(PHANTOM)).toEqual([
      "translate-x-4.5",
      "ml-6.5",
      "gap-12.5",
    ]);
  });

  it("leaves an exact length alone", () => {
    expect("translate-x-[1.125rem] ml-[1.625rem] max-w-[22rem]".match(PHANTOM)).toBeNull();
  });
});
