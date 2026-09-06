import { describe, expect, it } from "vitest";

import { countdown, isGood, relativeTime, summarise, timestamp } from "./format";

const NOW = new Date("2026-09-06T12:00:00Z");

describe("relativeTime", () => {
  it("says never when nothing has happened", () => {
    expect(relativeTime(null, NOW)).toBe("never");
  });

  it("rounds the last minute to just now", () => {
    expect(relativeTime("2026-09-06T11:59:30Z", NOW)).toBe("just now");
  });

  it("counts minutes", () => {
    expect(relativeTime("2026-09-06T11:20:00Z", NOW)).toBe("40m ago");
  });

  it("counts hours", () => {
    expect(relativeTime("2026-09-06T09:00:00Z", NOW)).toBe("3h ago");
  });

  it("counts days", () => {
    expect(relativeTime("2026-09-01T12:00:00Z", NOW)).toBe("5d ago");
  });

  it("does not report a future time as a negative age", () => {
    expect(relativeTime("2026-09-07T12:00:00Z", NOW)).toBe("just now");
  });
});

describe("countdown", () => {
  it("has nothing to say without a deadline", () => {
    expect(countdown(null, NOW)).toBe("—");
  });

  it("says a passed deadline is overdue", () => {
    expect(countdown("2026-09-05T12:00:00Z", NOW)).toBe("overdue");
  });

  it("counts whole days", () => {
    expect(countdown("2026-09-13T12:00:00Z", NOW)).toBe("7 days");
  });

  it("uses the singular for one day", () => {
    expect(countdown("2026-09-07T13:00:00Z", NOW)).toBe("1 day");
  });

  it("counts hours inside a day", () => {
    expect(countdown("2026-09-06T20:00:00Z", NOW)).toBe("8h");
  });

  it("counts minutes inside an hour", () => {
    expect(countdown("2026-09-06T12:30:00Z", NOW)).toBe("30m");
  });

  it("never counts down to zero minutes while there is time left", () => {
    expect(countdown("2026-09-06T12:00:30Z", NOW)).toBe("1m");
  });
});

describe("timestamp", () => {
  it("writes the day first with the month named", () => {
    // A numeric short date is read differently on either side of the Atlantic. The month
    // abbreviation itself varies with the ICU version ("Sep" or "Sept"), which is fine —
    // what matters is that it is a name and that the day comes first.
    expect(timestamp("2026-09-07T08:05:00Z")).toMatch(/^7 Sept? 2026,/);
  });

  it("uses a 24-hour clock", () => {
    expect(timestamp("2026-09-07T18:05:00Z")).not.toMatch(/[AP]M/);
  });

  it("has nothing to say about a missing time", () => {
    expect(timestamp(null)).toBe("—");
  });
});

describe("isGood", () => {
  it("counts only ok as a working session", () => {
    expect(isGood("ok")).toBe(true);
    expect(isGood("login_expired")).toBe(false);
    expect(isGood("network_error")).toBe(false);
  });
});

describe("summarise", () => {
  it("invites the first site when there are none", () => {
    expect(summarise([])).toBe("No sites yet");
  });

  it("counts each state", () => {
    expect(summarise(["alive", "alive", "lapsed"])).toBe("3 sites · 2 alive · 1 lapsed");
  });

  it("uses the singular for one site", () => {
    expect(summarise(["alive"])).toBe("1 site · 1 alive");
  });

  it("puts the states needing attention after the healthy count", () => {
    const summary = summarise(["lapsed", "alive", "at_risk"]);

    expect(summary.indexOf("alive")).toBeLessThan(summary.indexOf("due soon"));
    expect(summary.indexOf("due soon")).toBeLessThan(summary.indexOf("lapsed"));
  });

  it("leaves out states nothing is in", () => {
    expect(summarise(["alive"])).not.toContain("lapsed");
  });
});
