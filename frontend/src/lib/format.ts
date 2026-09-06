/**
 * Turning timestamps and states into the words the interface uses.
 *
 * Dates are written day-first with the month named (`7 Sep 2026`): a purely numeric short
 * date is read differently on either side of the Atlantic, and this one is meant to be
 * unambiguous at a glance.
 */

import type { CheckOutcome, SiteStatus } from "../api/types";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** How long ago, in the roughest unit that is still useful. */
export function relativeTime(value: string | null, now: Date = new Date()): string {
  if (!value) return "never";
  const elapsed = now.getTime() - new Date(value).getTime();
  if (elapsed < 0) return "just now";
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m ago`;
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}h ago`;
  return `${Math.floor(elapsed / DAY)}d ago`;
}

/** How long until something happens, or that it already has. */
export function countdown(value: string | null, now: Date = new Date()): string {
  if (!value) return "—";
  const remaining = new Date(value).getTime() - now.getTime();
  if (remaining <= 0) return "overdue";
  if (remaining < HOUR) return `${Math.max(Math.floor(remaining / MINUTE), 1)}m`;
  if (remaining < DAY) return `${Math.floor(remaining / HOUR)}h`;
  const days = Math.floor(remaining / DAY);
  return `${days} ${days === 1 ? "day" : "days"}`;
}

// One formatter, fixed to en-GB: day first with the month named, and a 24-hour clock. The
// browser's own locale is deliberately not used — it would render the same instant as
// "9/7/2026, 10:05 AM" for one reader and "07/09/2026, 10:05" for another, and a numeric
// day/month pair is the one date format that cannot be read out loud unambiguously. The
// times are still shown in the reader's own zone, which is what a timestamp is for.
const timestampFormat = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

/** A full timestamp, day-first and with the month named. */
export function timestamp(value: string | null): string {
  if (!value) return "—";
  return timestampFormat.format(new Date(value));
}

export const statusLabels: Record<SiteStatus, string> = {
  unknown: "not checked",
  alive: "alive",
  at_risk: "due soon",
  lapsed: "lapsed",
  error: "unreachable",
};

/** The token colour each status is drawn in. */
export const statusColors: Record<SiteStatus, string> = {
  unknown: "text-unknown",
  alive: "text-alive",
  at_risk: "text-risk",
  lapsed: "text-lapsed",
  error: "text-risk",
};

export const outcomeLabels: Record<CheckOutcome, string> = {
  ok: "ok",
  login_expired: "session expired",
  pattern_missing: "page did not look logged in",
  http_error: "unexpected response",
  network_error: "could not connect",
};

/** Whether an outcome means the session is still good. */
export function isGood(outcome: CheckOutcome): boolean {
  return outcome === "ok";
}

/** A one-line summary of a set of sites, for the line above the table. */
export function summarise(statuses: SiteStatus[]): string {
  if (statuses.length === 0) return "No sites yet";
  const counts = statuses.reduce<Partial<Record<SiteStatus, number>>>((totals, status) => {
    totals[status] = (totals[status] ?? 0) + 1;
    return totals;
  }, {});
  const parts = [`${statuses.length} ${statuses.length === 1 ? "site" : "sites"}`];
  // Ordered by how much attention each state deserves, so the worst news is nearest the
  // count rather than wherever it happens to fall alphabetically.
  const order: SiteStatus[] = ["alive", "at_risk", "lapsed", "error", "unknown"];
  for (const status of order) {
    const count = counts[status];
    if (count) parts.push(`${count} ${statusLabels[status]}`);
  }
  return parts.join(" · ");
}
