/**
 * Adding and editing a site, in two steps.
 *
 * Two because the questions are of different kinds. The first step is what the site is and how
 * often to ask it — facts someone already knows. The second is how to tell a live session from
 * a dead one, which is the only part that needs thought, and which nobody can answer without
 * having seen the page both signed in and signed out. Putting them on one screen made the
 * whole form read as equally hard.
 *
 * Each step says which of its fields are needed and why, because the previous version's
 * hardest question — are these detection fields required? — was one the form never answered.
 * They are individually optional and collectively load-bearing: with none of them set, a check
 * can only report that the site answered, not that you are still logged in.
 */

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { emptySite, type DetectedRules, type Site, type SiteWrite } from "../api/types";
import { Modal } from "../components/Modal";
import {
  Button,
  Choice,
  Field,
  Input,
  Problem,
  Select,
  TextArea,
  Toggle,
} from "../components/ui";

/** How the second step's detection rules are being arrived at. */
type Approach = "detect" | "manual" | "none";

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
  const [step, setStep] = useState<1 | 2>(1);
  const [approach, setApproach] = useState<Approach>(() => initialApproach(site));
  const [found, setFound] = useState<DetectedRules | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);

  const set = <K extends keyof SiteWrite>(key: K, value: SiteWrite[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  // Empty text inputs are sent as null rather than "": the API treats an absent pattern as
  // "do not check this", and an empty string would be a pattern that matches everything.
  const text = (value: string) => (value.trim() === "" ? null : value);

  const detect = useMutation({
    mutationFn: () => api.detectRules(site!.id),
    onSuccess: (rules) => {
      setFound(rules);
      setDetectError(null);
      setDraft((current) => ({
        ...current,
        login_url_pattern: rules.login_url_pattern ?? null,
        success_pattern: rules.success_pattern ?? null,
        failure_pattern: rules.failure_pattern ?? null,
      }));
    },
    onError: (cause) =>
      setDetectError(
        cause instanceof ApiError ? cause.message : "The site could not be compared.",
      ),
  });

  const hasSession = site?.session != null;
  const rules = [draft.login_url_pattern, draft.success_pattern, draft.failure_pattern];
  const ruleCount = rules.filter(Boolean).length;
  // The one rule the form enforces: choosing to detect, and then detecting nothing, is a site
  // configured to notice nothing. Saying so is more use than a silently useless site.
  const blocked = approach !== "none" && ruleCount === 0;

  const submit = () => {
    if (approach === "none") {
      onSave({
        ...draft,
        login_url_pattern: null,
        success_pattern: null,
        failure_pattern: null,
      });
      return;
    }
    onSave(draft);
  };

  return (
    <Modal
      title={site ? `Edit ${site.name}` : "Add a site"}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={step === 1 ? onCancel : () => setStep(1)} type="button">
            {step === 1 ? "Cancel" : "Back"}
          </Button>
          {step === 1 ? (
            <Button tone="primary" type="submit" form="site-form">
              Next
            </Button>
          ) : (
            <Button
              tone="primary"
              type="submit"
              form="site-form"
              disabled={busy || blocked}
              title={blocked ? "Fill in a rule, or choose not to detect a dead session" : undefined}
            >
              {busy ? "Saving…" : site ? "Save changes" : "Add site"}
            </Button>
          )}
        </>
      }
    >
      <form
        id="site-form"
        className="flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          // The first step's button advances rather than saves, so the browser's own required
          // -field validation guards the crossing instead of a check written here.
          if (step === 1) {
            setStep(2);
            return;
          }
          submit();
        }}
      >
        <Steps current={step} />
        {error ? <Problem>{error}</Problem> : null}

        {step === 1 ? (
          <TheSite draft={draft} set={set} text={text} />
        ) : (
          <Detection
            draft={draft}
            set={set}
            text={text}
            approach={approach}
            onApproach={setApproach}
            hasSession={hasSession}
            isNew={site === null}
            found={found}
            detecting={detect.isPending}
            onDetect={() => detect.mutate()}
            detectError={detectError}
            ruleCount={ruleCount}
          />
        )}
      </form>
    </Modal>
  );
}

function Steps({ current }: { current: 1 | 2 }) {
  const labels = ["The site", "Spotting a dead session"];
  return (
    <ol className="flex gap-4 text-micro">
      {labels.map((label, index) => {
        const step = index + 1;
        const active = step === current;
        return (
          <li
            key={label}
            aria-current={active ? "step" : undefined}
            className={active ? "font-medium text-ink" : "text-muted"}
          >
            {step}. {label}
          </li>
        );
      })}
    </ol>
  );
}

type Setter = <K extends keyof SiteWrite>(key: K, value: SiteWrite[K]) => void;
type Text = (value: string) => string | null;

function TheSite({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <fieldset className="flex flex-col gap-4">
      <p className="text-small text-muted">
        What the site is, and how often to ask it. Everything here except the two marked optional
        is needed.
      </p>
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
            type="url"
            value={draft.ping_url}
            onChange={(event) => set("ping_url", event.target.value)}
            placeholder="e.g. https://example.org/home"
            autoComplete="off"
            required
          />
        </Field>
        <Field
          label="Login URL"
          hint="Optional. Where the browser opens when you log in — the ping URL is used if you leave this empty."
        >
          <Input
            type="url"
            value={draft.login_url ?? ""}
            onChange={(event) => set("login_url", text(event.target.value))}
            placeholder="e.g. https://example.org/login"
            autoComplete="off"
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
          hint="Optional. Days. Fill this in and lifeline counts down and warns you in time."
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
            onChange={(event) =>
              set("ping_method", event.target.value as SiteWrite["ping_method"])
            }
          >
            <option value="http">One HTTP request</option>
            <option value="browser">A browser</option>
          </Select>
        </Field>
      </div>
    </fieldset>
  );
}

function Detection({
  draft,
  set,
  text,
  approach,
  onApproach,
  hasSession,
  isNew,
  found,
  detecting,
  onDetect,
  detectError,
  ruleCount,
}: {
  draft: SiteWrite;
  set: Setter;
  text: Text;
  approach: Approach;
  onApproach: (value: Approach) => void;
  hasSession: boolean;
  isNew: boolean;
  found: DetectedRules | null;
  detecting: boolean;
  onDetect: () => void;
  detectError: string | null;
  ruleCount: number;
}) {
  return (
    <div className="flex flex-col gap-5">
      <fieldset className="flex flex-col gap-4">
        <p className="text-small text-muted">
          A check can always tell you the site answered. To know whether you are still{" "}
          <em>logged in</em>, it needs one thing that differs between a signed-in page and a
          signed-out one.
        </p>

        <Choice
          checked={approach === "detect"}
          onChange={() => onApproach("detect")}
          disabled={!hasSession}
          label="Work it out from my login"
          hint={
            hasSession
              ? "Fetches the page twice, signed in and signed out, and fills these in from the difference."
              : isNew
                ? "Available once you have logged in. Add the site, log in, then edit it and come back here."
                : "Log in to this site first — there is nothing to compare a signed-out page against."
          }
        >
          <div className="flex flex-col gap-3">
            <div>
              <Button type="button" onClick={onDetect} disabled={detecting}>
                {detecting ? "Comparing…" : found ? "Compare again" : "Compare the two"}
              </Button>
            </div>
            {detectError ? <Problem>{detectError}</Problem> : null}
            {found ? (
              <ul className="flex flex-col gap-1 text-micro text-muted">
                {found.notes?.map((note) => <li key={note}>{note}</li>)}
              </ul>
            ) : null}
            {found ? <Rules draft={draft} set={set} text={text} /> : null}
          </div>
        </Choice>

        <Choice
          checked={approach === "manual"}
          onChange={() => onApproach("manual")}
          label="Set them myself"
          hint="At least one. The first is the easiest to get right and catches nearly everything."
        >
          <Rules draft={draft} set={set} text={text} />
        </Choice>

        <Choice
          checked={approach === "none"}
          onChange={() => onApproach("none")}
          label="Don't detect a dead session"
          hint="Keeps pinging the site on schedule, but says nothing when the login stops working."
        />

        {approach !== "none" && ruleCount === 0 ? (
          <p className="text-small text-risk">
            Nothing is set yet, so a check could not tell a dead session from a live one.
          </p>
        ) : null}
      </fieldset>

      <fieldset className="flex flex-col gap-4 border-t border-line pt-4">
        <legend className="sr-only">What counts as a good response</legend>
        <div className="grid gap-4 sm:grid-cols-2">
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
          <Field
            label="Spread checks by"
            hint="Percent, so a site is not asked at the same time forever."
          >
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
    </div>
  );
}

function Rules({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field
        label="Login page looks like"
        hint="Text or a regex matched against the URL the request ends on."
      >
        <Input
          value={draft.login_url_pattern ?? ""}
          onChange={(event) => set("login_url_pattern", text(event.target.value))}
          placeholder="e.g. login.php"
          autoComplete="off"
        />
      </Field>
      <Field label="Page must contain" hint="Something only a logged-in page shows.">
        <Input
          value={draft.success_pattern ?? ""}
          onChange={(event) => set("success_pattern", text(event.target.value))}
          placeholder="e.g. Log out"
          autoComplete="off"
        />
      </Field>
      <Field label="Page must not contain" hint="Something only a logged-out page shows.">
        <Input
          value={draft.failure_pattern ?? ""}
          onChange={(event) => set("failure_pattern", text(event.target.value))}
          // An example, not an instruction: unprefixed, this field reads as asking the person to
          // type their password into it — and a browser may offer to fill it in.
          placeholder="e.g. Enter your password"
          autoComplete="off"
        />
      </Field>
    </div>
  );
}

/**
 * Which approach an existing site's settings represent.
 *
 * A site with no rules at all was configured that way deliberately or has never been finished;
 * either way "don't detect" describes what it currently does, and says so rather than showing
 * empty fields that look like an oversight.
 */
function initialApproach(site: Site | null): Approach {
  if (site === null) return "manual";
  const set = [site.login_url_pattern, site.success_pattern, site.failure_pattern].filter(Boolean);
  return set.length === 0 ? "none" : "manual";
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
