/**
 * The one place that talks to the API.
 *
 * Two things every caller would otherwise have to remember are handled here: a 409 means
 * this instance has not been set up yet (not that the request was wrong), and a 401 means
 * the session has gone. Both are conditions the whole app has to react to, so they are
 * raised as recognisable errors rather than left as status codes to be re-checked.
 */

import {
  ApiClient,
  ApiError,
  fieldMessages,
  NOT_AUTHENTICATED,
  type Query,
  SETUP_REQUIRED,
  writeHeader,
} from "@jmerhar/jigkit/api";

import type {
  Check,
  DetectedRules,
  Health,
  LoginSession,
  RuleTrial,
  RuleTrialResult,
  Settings,
  Site,
  SiteWrite,
  User,
} from "./types";

export { ApiError };

/** The instance has no administrator yet. */
export class SetupRequired extends Error {
  constructor() {
    super(SETUP_REQUIRED);
    this.name = "SetupRequired";
  }
}

/** Nobody is logged in. */
export class NotAuthenticated extends Error {
  constructor() {
    super(NOT_AUTHENTICATED);
    this.name = "NotAuthenticated";
  }
}

/**
 * Sent with every write. The API refuses a write without it, and a page on another site cannot
 * add it to a request without a CORS preflight the API never grants.
 */
export const WRITE_HEADER = writeHeader("lifeline");

/** The two refusals the whole app reacts to, as their own errors; anything else is an ApiError. */
function refused(status: number, reason: string): Error | undefined {
  if (status === 409 && reason === SETUP_REQUIRED) return new SetupRequired();
  if (status === 401) return new NotAuthenticated();
  return undefined;
}

// FastAPI answers a validation failure with a message per field, which is what tells someone
// what to fix, so those are shown rather than a bare "invalid".
const client = new ApiClient({ writeHeader: WRITE_HEADER, refused, invalid: fieldMessages });

function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  return client.request<T>(method, path, body, query);
}

export const api = {
  detectRules: (id: number) =>
    request<DetectedRules>("POST", `/sites/${id}/detect`),
  testRules: (id: number, rules: RuleTrial) =>
    request<RuleTrialResult>("POST", `/sites/${id}/test-rules`, rules),
  completeSetup: (payload: { username: string; password: string }) =>
    request<User>("POST", "/setup", payload),

  health: () => request<Health>("GET", "/health"),
  me: () => request<User>("GET", "/auth/me"),
  login: (payload: { username: string; password: string }) =>
    request<User>("POST", "/auth/login", payload),
  logout: () => request<{ detail: string }>("POST", "/auth/logout"),

  sites: () => request<Site[]>("GET", "/sites"),
  site: (id: number) => request<Site>("GET", `/sites/${id}`),
  createSite: (payload: SiteWrite) => request<Site>("POST", "/sites", payload),
  updateSite: (id: number, payload: SiteWrite) =>
    request<Site>("PUT", `/sites/${id}`, payload),
  deleteSite: (id: number) => request<void>("DELETE", `/sites/${id}`),
  checkNow: (id: number) => request<Check>("POST", `/sites/${id}/check`),
  siteChecks: (id: number, limit = 50) => request<Check[]>("GET", `/sites/${id}/checks`, undefined, { limit }),
  importSession: (id: number, payload: { text: string; user_agent?: string | null }) =>
    request<{ detail: string }>("POST", `/sites/${id}/session/import`, payload),
  forgetSession: (id: number) =>
    request<{ detail: string }>("DELETE", `/sites/${id}/session`),
  openLogin: (id: number) =>
    request<LoginSession>("POST", `/sites/${id}/login-session`),

  saveLogin: (token: string) =>
    request<{ detail: string }>("POST", `/browser/${token}/save`),
  closeLogin: (token: string) =>
    request<{ detail: string }>("DELETE", `/browser/${token}`),

  checks: (limit = 100) => request<Check[]>("GET", "/checks", undefined, { limit }),
  settings: () => request<Settings>("GET", "/settings"),
  saveSettings: (payload: Settings) =>
    request<Settings>("PUT", "/settings", payload),
  testNotification: () =>
    request<{ detail: string }>("POST", "/settings/test-notification"),
};
