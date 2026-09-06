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
