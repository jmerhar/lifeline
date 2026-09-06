/**
 * The header: where you are, where else you can go, and the theme switch.
 *
 * A top bar rather than a sidebar. There are three screens, and a sidebar would spend a
 * column of a data-dense table's width on three links.
 */

import { Moon, Sun } from "lucide-react";
import { NavLink } from "react-router-dom";

import { Wordmark } from "./Mark";
import type { Theme } from "../hooks/useTheme";

const links = [
  { to: "/", label: "Sites" },
  { to: "/history", label: "History" },
  { to: "/settings", label: "Settings" },
];

export function TopNav({
  theme,
  onToggleTheme,
  onLogout,
}: {
  theme: Theme;
  onToggleTheme: () => void;
  onLogout?: () => void;
}) {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-14 max-w-[1200px] items-center gap-6 px-4">
        <Wordmark />
        <nav className="flex items-center gap-1" aria-label="Main">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/"}
              className={({ isActive }) =>
                `rounded px-2.5 py-1.5 text-small transition-colors ${
                  isActive ? "bg-raised text-ink" : "text-muted hover:text-ink"
                }`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={onToggleTheme}
            className="rounded p-2 text-muted hover:text-ink"
            aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          {onLogout ? (
            <button
              type="button"
              onClick={onLogout}
              className="rounded px-2.5 py-1.5 text-small text-muted hover:text-ink"
            >
              Log out
            </button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
