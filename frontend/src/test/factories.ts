/** Builders for the API shapes, so a test names only what it cares about. */

import type { Check, Settings, Site } from "../api/types";

export function makeSite(overrides: Partial<Site> = {}): Site {
  return {
    id: 1,
    name: "example",
    ping_url: "https://example.org/home",
    login_url: "https://example.org/login.php",
    enabled: true,
    interval_days: 7,
    jitter_percent: 10,
    ping_method: "http",
    user_agent: null,
    favicon: null,
    expected_status: 200,
    follow_redirects: true,
    login_url_pattern: "login.php",
    success_pattern: null,
    failure_pattern: null,
    inactivity_limit_days: null,
    notes: null,
    status: "alive",
    consecutive_failures: 0,
    last_check_at: "2026-09-06T10:00:00Z",
    last_ok_at: "2026-09-06T10:00:00Z",
    next_check_at: "2026-09-13T10:00:00Z",
    deadline_at: null,
    session: {
      captured_at: "2026-09-01T09:00:00Z",
      captured_via: "browser",
      rotated_at: "2026-09-06T10:00:00Z",
      earliest_expiry: "2027-01-01T00:00:00Z",
      cookie_names: ["session", "uid"],
    },
    pulse: ["ok", "ok", "ok"],
    ...overrides,
  };
}

export function makeCheck(overrides: Partial<Check> = {}): Check {
  return {
    id: 1,
    site_id: 1,
    started_at: "2026-09-06T10:00:00Z",
    outcome: "ok",
    status_code: 200,
    final_url: "https://example.org/home",
    duration_ms: 412,
    detail: null,
    ...overrides,
  };
}

export function makeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    apprise_urls: "",
    notify_on_lapsed: true,
    notify_on_recovered: true,
    notify_on_errors: true,
    notify_on_cookie_expiry: true,
    notify_on_deadline: true,
    notify_cooldown_hours: 24,
    warning_lead_days: 7,
    error_threshold: 3,
    default_interval_days: 7,
    retention_days: 90,
    browser_idle_timeout_minutes: 15,
    log_level: "INFO",
    ...overrides,
  };
}
