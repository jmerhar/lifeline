/**
 * Which palette the interface is drawn in.
 *
 * Stored per browser and applied to the root element, so a reload does not flash the other
 * theme. Nothing is stored until someone chooses: with no preference the browser's own
 * setting wins, which is what most people want and never have to ask for.
 */

import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "lifeline-theme";

function preferred(): Theme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    // Private browsing, or storage switched off. The browser's preference still applies.
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(preferred);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      try {
        window.localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Not being able to remember the choice is not a reason to refuse to make it.
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}
