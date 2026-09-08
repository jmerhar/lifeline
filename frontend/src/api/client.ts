/**
 * The one place that talks to the API.
 *
 * Two things every caller would otherwise have to remember are handled here: a 409 means
 * this instance has not been set up yet (not that the request was wrong), and a 401 means
 * the session has gone. Both are conditions the whole app has to react to, so they are
 * raised as recognisable errors rather than left as status codes to be re-checked.
 */

import type {
  Check,
  DetectedRules,
  LoginSession,
  RuleTrial,
  RuleTrialResult,
  Settings,
  Site,
  SiteWrite,
  SetupState,
  User,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The instance has no administrator yet. */
export class SetupRequired extends Error {
  constructor() {
    super("setup_required");
    this.name = "SetupRequired";
  }
}

/** Nobody is logged in. */
export class NotAuthenticated extends Error {
  constructor() {
    super("not_authenticated");
    this.name = "NotAuthenticated";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
    // The session is a cookie, and a cross-origin dev server would otherwise drop it.
    credentials: "same-origin",
  });

  if (response.status === 409) {
    const body = await safeJson(response);
    if (body?.detail === "setup_required") throw new SetupRequired();
    throw new ApiError(response.status, detailOf(body) ?? "conflict");
  }
  if (response.status === 401) throw new NotAuthenticated();
  if (!response.ok) {
    throw new ApiError(response.status, detailOf(await safeJson(response)) ?? response.statusText);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function safeJson(response: Response): Promise<{ detail?: unknown } | null> {
  try {
    return await response.json();
  } catch {
    // An error page from a proxy rather than the API; the status is all there is to go on.
    return null;
  }
}

/**
 * The human-readable half of an error body.
 *
 * FastAPI answers a validation failure with a list of per-field objects rather than a
 * string, and rendering that list raw puts `[object Object]` in front of someone who just
 * mistyped a URL.
 */
function detailOf(body: { detail?: unknown } | null): string | null {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : null))
      .filter((message): message is string => Boolean(message));
    if (messages.length) return messages.join("; ");
  }
  return null;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  detectRules: (id: number) =>
    request<DetectedRules>(`/sites/${id}/detect`, { method: "POST" }),
  testRules: (id: number, rules: RuleTrial) =>
    request<RuleTrialResult>(`/sites/${id}/test-rules`, { method: "POST", ...json(rules) }),
  setupState: () => request<SetupState>("/setup"),
  completeSetup: (payload: { username: string; password: string; token?: string }) =>
    request<User>("/setup", { method: "POST", ...json(payload) }),

  me: () => request<User>("/auth/me"),
  login: (payload: { username: string; password: string }) =>
    request<User>("/auth/login", { method: "POST", ...json(payload) }),
  logout: () => request<{ detail: string }>("/auth/logout", { method: "POST" }),

  sites: () => request<Site[]>("/sites"),
  site: (id: number) => request<Site>(`/sites/${id}`),
  createSite: (payload: SiteWrite) => request<Site>("/sites", { method: "POST", ...json(payload) }),
  updateSite: (id: number, payload: SiteWrite) =>
    request<Site>(`/sites/${id}`, { method: "PUT", ...json(payload) }),
  deleteSite: (id: number) => request<void>(`/sites/${id}`, { method: "DELETE" }),
  checkNow: (id: number) => request<Check>(`/sites/${id}/check`, { method: "POST" }),
  siteChecks: (id: number, limit = 50) => request<Check[]>(`/sites/${id}/checks?limit=${limit}`),
  importSession: (id: number, payload: { text: string; user_agent?: string | null }) =>
    request<{ detail: string }>(`/sites/${id}/session/import`, { method: "POST", ...json(payload) }),
  forgetSession: (id: number) =>
    request<{ detail: string }>(`/sites/${id}/session`, { method: "DELETE" }),
  openLogin: (id: number) =>
    request<LoginSession>(`/sites/${id}/login-session`, { method: "POST" }),

  saveLogin: (token: string) =>
    request<{ detail: string }>(`/browser/${token}/save`, { method: "POST" }),
  closeLogin: (token: string) =>
    request<{ detail: string }>(`/browser/${token}`, { method: "DELETE" }),

  checks: (limit = 100) => request<Check[]>(`/checks?limit=${limit}`),
  settings: () => request<Settings>("/settings"),
  saveSettings: (payload: Settings) =>
    request<Settings>("/settings", { method: "PUT", ...json(payload) }),
  testNotification: () =>
    request<{ detail: string }>("/settings/test-notification", { method: "POST" }),
};
