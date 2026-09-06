/**
 * Adding and editing a site.
 *
 * The fields are in two groups: what to ask, and how to tell whether the answer means the
 * session is still good. The second group is the part that actually needs thought, so each
 * field says what it is for rather than only what it is called.
 */

import { useState } from "react";

import { emptySite, type Site, type SiteWrite } from "../api/types";
import { Modal } from "../components/Modal";
import { Button, Field, Input, Problem, Select, TextArea, Toggle } from "../components/ui";

export function SiteForm({
  site,
  defaultIntervalDays,
  onCancel,
  onSave,
  error,
  busy,
}: {
  site: Site | null;
  defaultIntervalDays: number;
  onCancel: () => void;
  onSave: (payload: SiteWrite) => void;
  error?: string | null;
  busy?: boolean;
}) {
  const [draft, setDraft] = useState<SiteWrite>(() =>
    site ? toWrite(site) : { ...emptySite, interval_days: defaultIntervalDays },
  );

  const set = <K extends keyof SiteWrite>(key: K, value: SiteWrite[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  // Empty text inputs are sent as null rather than "": the API treats an absent pattern as
  // "do not check this", and an empty string would be a pattern that matches everything.
  const text = (value: string) => (value.trim() === "" ? null : value);

  return (
    <Modal
      title={site ? `Edit ${site.name}` : "Add a site"}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel} type="button">
            Cancel
          </Button>
          <Button tone="primary" type="submit" form="site-form" disabled={busy}>
            {busy ? "Saving…" : site ? "Save changes" : "Add site"}
          </Button>
        </>
      }
    >
      <form
        id="site-form"
        className="flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          onSave(draft);
        }}
      >
        {error ? <Problem>{error}</Problem> : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" hint="Yours to choose. Add a site twice for two accounts.">
            <Input
              value={draft.name}
              onChange={(event) => set("name", event.target.value)}
              required
              autoFocus
            />
          </Field>
          <Field label="Ping URL" hint="A page that only renders when you are logged in.">
            <Input
              value={draft.ping_url}
              onChange={(event) => set("ping_url", event.target.value)}
              placeholder="https://example.org/home"
              type="url"
              required
            />
          </Field>
          <Field label="Login URL" hint="Where the browser opens when you log in. Optional.">
            <Input
              value={draft.login_url ?? ""}
              onChange={(event) => set("login_url", text(event.target.value))}
              placeholder="https://example.org/login"
            />
          </Field>
          <Field label="Check every" hint="Days between checks.">
            <Input
              type="number"
              min={1}
              max={365}
              value={draft.interval_days}
              onChange={(event) => set("interval_days", Number(event.target.value))}
              required
            />
          </Field>
          <Field
            label="Site disables an account after"
            hint="Days. Leave empty if the site has no such rule."
          >
            <Input
              type="number"
              min={1}
              max={3650}
              value={draft.inactivity_limit_days ?? ""}
              onChange={(event) =>
                set(
                  "inactivity_limit_days",
                  event.target.value === "" ? null : Number(event.target.value),
                )
              }
            />
          </Field>
          <Field label="How to ping" hint="Use a browser only for sites that need JavaScript.">
            <Select
              value={draft.ping_method}
              onChange={(event) => set("ping_method", event.target.value as SiteWrite["ping_method"])}
            >
              <option value="http">One HTTP request</option>
              <option value="browser">A real browser</option>
            </Select>
          </Field>
        </div>

        <fieldset className="flex flex-col gap-4 border-t border-line pt-4">
          <legend className="sr-only">Telling a live session from a dead one</legend>
          <p className="text-small text-muted">
            How lifeline decides whether the session still works. Fill in whichever of these the
            site gives you — the first two catch nearly everything.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Login page looks like"
              hint="Text or a regex matched against the URL the request ends on."
            >
              <Input
                value={draft.login_url_pattern ?? ""}
                onChange={(event) => set("login_url_pattern", text(event.target.value))}
                placeholder="login.php"
              />
            </Field>
            <Field label="Page must contain" hint="Something only a logged-in page shows.">
              <Input
                value={draft.success_pattern ?? ""}
                onChange={(event) => set("success_pattern", text(event.target.value))}
                placeholder="Log out"
              />
            </Field>
            <Field label="Page must not contain" hint="Something only a logged-out page shows.">
              <Input
                value={draft.failure_pattern ?? ""}
                onChange={(event) => set("failure_pattern", text(event.target.value))}
                placeholder="Enter your password"
              />
            </Field>
            <Field label="Expected status" hint="The HTTP status a good response has.">
              <Input
                type="number"
                min={100}
                max={599}
                value={draft.expected_status}
                onChange={(event) => set("expected_status", Number(event.target.value))}
                required
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Toggle
              checked={draft.follow_redirects}
              onChange={(value) => set("follow_redirects", value)}
              label="Follow redirects"
              hint="Off if the site answers with a redirect when the session is fine."
            />
            <Toggle
              checked={draft.enabled}
              onChange={(value) => set("enabled", value)}
              label="Check on a schedule"
              hint="Off to keep the site listed but stop pinging it."
            />
          </div>
        </fieldset>

        <details className="border-t border-line pt-4">
          <summary className="cursor-pointer text-small text-muted">Rarely needed</summary>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field label="Spread checks by" hint="Percent, so a site is not asked at the same time forever.">
              <Input
                type="number"
                min={0}
                max={50}
                value={draft.jitter_percent}
                onChange={(event) => set("jitter_percent", Number(event.target.value))}
              />
            </Field>
            <Field
              label="User-Agent"
              hint="Captured when you log in. Changing it can invalidate the session."
            >
              <Input
                value={draft.user_agent ?? ""}
                onChange={(event) => set("user_agent", text(event.target.value))}
              />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Notes">
                <TextArea
                  rows={3}
                  value={draft.notes ?? ""}
                  onChange={(event) => set("notes", text(event.target.value))}
                />
              </Field>
            </div>
          </div>
        </details>
      </form>
    </Modal>
  );
}

function toWrite(site: Site): SiteWrite {
  const { name, ping_url, login_url, enabled, interval_days, jitter_percent } = site;
  return {
    name,
    ping_url,
    login_url,
    enabled,
    interval_days,
    jitter_percent,
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
