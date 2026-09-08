/**
 * The shapes the API sends and accepts.
 *
 * Derived from the API's own OpenAPI schema, not written out again here: the schema is
 * generated from the FastAPI application by `make openapi`, committed, and checked by CI, so a
 * response shape cannot change without either this file's types changing with it or the build
 * failing. Hand-written copies drift silently, and the symptom is a field that reads as
 * undefined at runtime.
 *
 * Only aliases and genuine additions belong here. To change a shape, change the Pydantic model
 * and run `make openapi`.
 */

import type { components } from "../types/api";

type Schema = components["schemas"];

export type SiteStatus = Schema["SiteStatus"];
export type CheckOutcome = Schema["CheckOutcome"];
export type PingMethod = Schema["PingMethod"];
export type CaptureMethod = Schema["CaptureMethod"];

export type SessionRead = Schema["SessionRead"];
export type SiteWrite = Schema["SiteWrite"];
export type Site = Schema["SiteRead"];
export type Check = Schema["CheckRead"];
export type Settings = Schema["SettingsRead"];
export type SetupState = Schema["SetupState"];
export type User = Schema["UserRead"];
export type LoginSession = Schema["LoginSessionRead"];
export type DetectedRules = Schema["DetectedRules"];
export type RuleTrial = Schema["RuleTrial"];
export type RuleTrialResult = Schema["RuleTrialResult"];

/**
 * A blank site, for the add form.
 *
 * A value rather than a type, so it cannot come from the schema — but every field is named,
 * so a field added to SiteWrite makes this fail to compile until it is given a default.
 */
export const emptySite: Required<SiteWrite> = {
  name: "",
  ping_url: "",
  login_url: null,
  enabled: true,
  interval_days: 7,
  jitter_percent: 10,
  ping_method: "http",
  user_agent: null,
  expected_status: 200,
  follow_redirects: true,
  login_url_pattern: null,
  success_pattern: null,
  failure_pattern: null,
  inactivity_limit_days: null,
  notes: null,
};

/**
 * The writable half of a site, for a form or for changing one field.
 *
 * Every field is named rather than spread from the site, so the request carries exactly what the
 * API accepts and a read-only field added to SiteRead cannot leak into an update.
 */
export function toWrite(site: Site): SiteWrite {
  return {
    name: site.name,
    ping_url: site.ping_url,
    login_url: site.login_url,
    enabled: site.enabled,
    interval_days: site.interval_days,
    jitter_percent: site.jitter_percent,
    ping_method: site.ping_method,
    user_agent: site.user_agent,
    expected_status: site.expected_status,
    follow_redirects: site.follow_redirects,
    login_url_pattern: site.login_url_pattern,
    success_pattern: site.success_pattern,
    failure_pattern: site.failure_pattern,
    inactivity_limit_days: site.inactivity_limit_days,
    notes: site.notes,
  };
}
