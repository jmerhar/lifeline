/** Which palette is used, and how the choice is remembered. */

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "./useTheme";

function withPreference(light: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({ matches: light, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
});

describe("useTheme", () => {
  it("follows the browser's preference when nothing has been chosen", () => {
    withPreference(true);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("light");
  });

  it("defaults to dark when the browser prefers dark", () => {
    withPreference(false);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
  });

  it("defaults to dark where matchMedia is unavailable", () => {
    vi.stubGlobal("matchMedia", undefined);

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
  });

  it("uses a stored choice over the browser's preference", () => {
    withPreference(false);
    window.localStorage.setItem("lifeline-theme", "light");

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("light");
  });

  it("applies the theme to the document", () => {
    withPreference(false);

    renderHook(() => useTheme());

    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("remembers a change", () => {
    withPreference(false);
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggle());

    expect(result.current.theme).toBe("light");
    expect(window.localStorage.getItem("lifeline-theme")).toBe("light");
  });

  it("still switches when the choice cannot be stored", () => {
    // Private browsing, or site data switched off. Refusing to change the theme because it
    // cannot be remembered would be the wrong trade.
    withPreference(false);
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggle());

    expect(result.current.theme).toBe("light");
  });

  it("ignores an unreadable stored value", () => {
    withPreference(false);
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });

    const { result } = renderHook(() => useTheme());

    expect(result.current.theme).toBe("dark");
  });
});
