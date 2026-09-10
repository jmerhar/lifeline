/**
 * Adding and editing a site.
 *
 * The two are different shapes because they are different situations. Adding is a sequence —
 * describe the site, log into it, then say how a dead session will be spotted — and the last of
 * those cannot be answered before the middle one: nobody knows what distinguishes a signed-in
 * page from a signed-out one without having seen the page. So adding asks only what the site is
 * and hands straight over to the login, which is what makes the rest answerable.
 *
 * Editing is not a sequence. Everything is already set and someone has come to change one
 * particular thing, so it is tabs: no order is implied and nothing has to be walked past.
 */

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import {
  emptySite,
  toWrite,
  type DetectedRules,
  type RuleOutcome,
  type RuleTrialResult,
  type Site,
  type SiteWrite,
} from "../api/types";
import { notACredential } from "../components/autofill";
import { Modal } from "../components/Modal";
import {
  Button,
  Field,
  Input,
  Problem,
  Select,
  TextArea,
  Toggle,
} from "../components/ui";

/**
 * Whether this site is watched for a dead session at all.
 *
 * Not how its rules were arrived at. Filling them in by hand and having the comparison fill them
 * in leave the identical form behind, so offering that as a choice asked a question with no
 * consequence — and let someone switch between two states that differed in nothing.
 */
export type Watching = "yes" | "no";

/** The panels an existing site's settings are divided into. */
export type Tab = "site" | "detection" | "advanced";

const TABS: { id: Tab; label: string }[] = [
  { id: "site", label: "The site" },
  { id: "detection", label: "Spotting a dead session" },
  { id: "advanced", label: "Advanced" },
];

export function SiteForm({
  site,
  defaultIntervalDays,
  initialTab = "site",
  compareOnOpen = false,
  onCancel,
  onSave,
  error,
  busy,
}: {
  site: Site | null;
  defaultIntervalDays: number;
  /** Which panel to open on. The login flow lands on detection, having just made it answerable. */
  initialTab?: Tab;
  /**
   * Run the comparison as the panel opens.
   *
   * Asked for by the login flow: someone who has just logged in has nothing to add by hand, and
   * everything the comparison needs now exists.
   */
  compareOnOpen?: boolean;
  onCancel: () => void;
  onSave: (payload: SiteWrite) => void;
  error?: string | null;
  busy?: boolean;
}) {
  const [draft, setDraft] = useState<SiteWrite>(() =>
    site ? toWrite(site) : { ...emptySite, interval_days: defaultIntervalDays },
  );
  const [tab, setTab] = useState<Tab>(initialTab);
  const [watching, setWatching] = useState<Watching>(() => watchingFor(site));
  const [found, setFound] = useState<DetectedRules | null>(null);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [trialError, setTrialError] = useState<string | null>(null);

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
        // Where a signed-out request landed is the login page, and what a check consults follows
        // from that on its own — there is no pattern to fill in alongside it.
        login_url: rules.login_url ?? current.login_url,
        success_pattern: rules.success_pattern ?? null,
        failure_pattern: rules.failure_pattern ?? null,
      }));
      // Something was found, so this site is being watched — whatever the checkbox said before
      // there was anything to watch with.
      if (rules.login_url || rules.success_pattern || rules.failure_pattern) setWatching("yes");
    },
    onError: (cause) =>
      setDetectError(cause instanceof ApiError ? cause.message : "The site could not be compared."),
  });

  const tryOut = useMutation({
    mutationFn: () =>
      api.testRules(site!.id, {
        login_url_pattern: draft.login_url_pattern,
        success_pattern: draft.success_pattern,
        failure_pattern: draft.failure_pattern,
        expected_status: draft.expected_status,
        follow_redirects: draft.follow_redirects,
      }),
    onError: (cause) =>
      setTrialError(cause instanceof ApiError ? cause.message : "The rules could not be tried."),
    onMutate: () => setTrialError(null),
  });

  const isNew = site === null;
  const hasSession = site?.session != null;

  // Fired once. A dependency list including the mutation would run it again on every render that
  // changed its identity, which is a browser fetch per keystroke.
  const compared = useRef(false);
  useEffect(() => {
    if (compareOnOpen && hasSession && !compared.current) {
      compared.current = true;
      detect.mutate();
    }
  }, [compareOnOpen, hasSession, detect]);

  const signals = countSignals(draft);
  // Watching a site and giving it nothing to watch with leaves it configured to notice nothing
  // while looking configured. Choosing not to watch it is a real answer and is never blocked,
  // and neither applies while adding, where the question has not been asked yet.
  const blocked = !isNew && watching === "yes" && signals === 0;

  const submit = () =>
    onSave(
      watching === "no"
        ? { ...draft, login_url_pattern: null, success_pattern: null, failure_pattern: null }
        : draft,
    );

  return (
    <Modal
      title={isNew ? "Add a site" : `Edit ${site.name}`}
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel} type="button">
            Cancel
          </Button>
          <Button
            tone="primary"
            type="submit"
            form="site-form"
            disabled={busy || blocked}
            title={blocked ? "Give it something to check, or turn detection off" : undefined}
          >
            {busy ? "Saving…" : isNew ? "Add site and log in" : "Save changes"}
          </Button>
        </>
      }
    >
      <form
        id="site-form"
        className="flex flex-col gap-5"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {error ? <Problem>{error}</Problem> : null}

        {isNew ? (
          <>
            <p className="text-small text-muted">
              What the site is. Saving opens a browser so you can log in — after that lifeline works
              out how to tell a live session from a dead one by itself.
            </p>
            <TheSite draft={draft} set={set} text={text} />
          </>
        ) : (
          <>
            <Tabs current={tab} onChange={setTab} />
            {tab === "site" ? <TheSite draft={draft} set={set} text={text} /> : null}
            {tab === "detection" ? (
              <Detection
                draft={draft}
                set={set}
                text={text}
                watching={watching}
                onWatching={setWatching}
                hasSession={hasSession}
                found={found}
                detecting={detect.isPending}
                onDetect={() => detect.mutate()}
                detectError={detectError}
                signals={signals}
                trial={tryOut.data ?? null}
                trialError={trialError}
                trying={tryOut.isPending}
                onTry={() => tryOut.mutate()}
              />
            ) : null}
            {tab === "advanced" ? <Advanced draft={draft} set={set} text={text} /> : null}
          </>
        )}
      </form>
    </Modal>
  );
}

function Tabs({ current, onChange }: { current: Tab; onChange: (tab: Tab) => void }) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-line">
      {TABS.map(({ id, label }) => {
        const active = id === current;
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(id)}
            className={`-mb-px border-b-2 px-3 py-2 text-small ${
              active ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

type Setter = <K extends keyof SiteWrite>(key: K, value: SiteWrite[K]) => void;
type Text = (value: string) => string | null;

function TheSite({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <fieldset className="grid gap-4 sm:grid-cols-2">
      <Field label="Name" hint="Yours to choose. Add a site twice for two accounts.">
        <Input
          value={draft.name}
          onChange={(event) => set("name", event.target.value)}
          required
          autoFocus
          {...notACredential}
        />
      </Field>
      <Field label="Ping URL" hint="A page that only renders when you are logged in.">
        <Input
          type="url"
          value={draft.ping_url}
          onChange={(event) => set("ping_url", event.target.value)}
          placeholder="e.g. https://example.org/home"
          required
          {...notACredential}
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
          onChange={(event) => set("ping_method", event.target.value as SiteWrite["ping_method"])}
        >
          <option value="http">One HTTP request</option>
          <option value="browser">A browser</option>
        </Select>
      </Field>
      <div className="sm:col-span-2">
        <Field label="Notes" hint="Optional. Anything worth remembering about this account.">
          <TextArea
            rows={3}
            value={draft.notes ?? ""}
            onChange={(event) => set("notes", text(event.target.value))}
            {...notACredential}
          />
        </Field>
      </div>
    </fieldset>
  );
}

function Detection({
  draft,
  set,
  text,
  watching,
  onWatching,
  hasSession,
  found,
  detecting,
  onDetect,
  detectError,
  signals,
  trial,
  trialError,
  trying,
  onTry,
}: {
  draft: SiteWrite;
  set: Setter;
  text: Text;
  watching: Watching;
  onWatching: (value: Watching) => void;
  hasSession: boolean;
  found: DetectedRules | null;
  detecting: boolean;
  onDetect: () => void;
  detectError: string | null;
  signals: number;
  trial: RuleTrialResult | null;
  trialError: string | null;
  trying: boolean;
  onTry: () => void;
}) {
  return (
    <div className="flex flex-col gap-5">
      <p className="text-small text-muted">
        A check can always tell you the site answered. To know whether you are still{" "}
        <em>logged in</em>, it needs one thing that differs between a signed-in page and a
        signed-out one.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={onDetect} disabled={detecting || !hasSession}>
          {detecting ? "Comparing…" : found ? "Compare again" : "Work it out from my login"}
        </Button>
        <span className="text-micro text-muted">
          {hasSession
            ? "Fetches the page signed in and signed out, and fills in what differs."
            : "Log in to this site first — there is nothing to compare a signed-out page against."}
        </span>
      </div>

      {detectError ? <Problem>{detectError}</Problem> : null}
      {found ? (
        <ul className="flex flex-col gap-1 text-micro text-muted">
          {found.notes?.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}

      {watching === "yes" ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Page must contain" hint="Something only a logged-in page shows.">
              <Input
                value={draft.success_pattern ?? ""}
                onChange={(event) => set("success_pattern", text(event.target.value))}
                placeholder="e.g. Log out"
                {...notACredential}
              />
            </Field>
            <Field label="Page must not contain" hint="Something only a logged-out page shows.">
              <Input
                value={draft.failure_pattern ?? ""}
                onChange={(event) => set("failure_pattern", text(event.target.value))}
                // Names no password: a placeholder mentioning one gets the field classified as a
                // credential, which makes a password manager both fill it in and offer to save a
                // login for the whole form. "Remember me" belongs to a login page just as well.
                placeholder="e.g. Remember me"
                {...notACredential}
              />
            </Field>
          </div>

          {draft.login_url ? (
            <p className="text-micro text-muted">
              A signed-out request is also expected to end up at{" "}
              <span className="font-mono">{draft.login_url}</span>, which counts on its own. Change
              it under Advanced.
            </p>
          ) : null}

          {signals === 0 ? (
            <p className="text-small text-risk">
              Nothing is set yet, so a check could not tell a dead session from a live one.
            </p>
          ) : null}

          <Trial
            hasSession={hasSession}
            signals={signals}
            busy={trying}
            result={trial}
            error={trialError}
            onRun={onTry}
          />
        </>
      ) : null}

      <div className="border-t border-line pt-4">
        <Toggle
          checked={watching === "no"}
          onChange={(off) => onWatching(off ? "no" : "yes")}
          label="Don't detect a dead session"
          hint="Keeps pinging the site on schedule, but says nothing when the login stops working."
        />
      </div>
    </div>
  );
}

function Trial({
  hasSession,
  signals,
  busy,
  result,
  error,
  onRun,
}: {
  hasSession: boolean;
  signals: number;
  busy: boolean;
  result: RuleTrialResult | null;
  error: string | null;
  onRun: () => void;
}) {
  return (
    <div className="flex flex-col gap-3 border-t border-line pt-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" onClick={onRun} disabled={busy || !hasSession || signals === 0}>
          {busy ? "Trying…" : "Try these rules"}
        </Button>
        <span className="text-micro text-muted">
          {hasSession
            ? "Fetches the page signed in and signed out, and judges both the way a check would."
            : "There is no working session to try these against yet."}
        </span>
      </div>

      {error ? <Problem>{error}</Problem> : null}

      {result ? (
        <dl className="flex flex-col gap-1 text-micro">
          {result.rules?.map((rule) => (
            <div key={rule.rule} className="flex flex-wrap gap-x-2">
              <dt className="text-muted">{RULE_LABELS[rule.rule]}</dt>
              <dd className={rule.helps ? "text-alive" : "text-risk"}>{ruleNote(rule)}</dd>
            </div>
          ))}
          <Outcome
            label="Signed in, a check would say"
            outcome={result.live_outcome}
            detail={result.live_detail}
            good={result.live_outcome === "ok"}
          />
          <Outcome
            label="Signed out, a check would say"
            outcome={result.dead_outcome}
            detail={result.dead_detail}
            good={result.dead_outcome !== "ok"}
          />
          <p className={`mt-1 text-small ${result.works ? "text-alive" : "text-risk"}`}>
            {result.works
              ? "These rules would notice a dead session."
              : result.live_outcome !== "ok"
                ? "These rules report a problem even while the session works, so every check would fail."
                : "These rules pass both pages, so a dead session would never be noticed."}
          </p>
        </dl>
      ) : null}
    </div>
  );
}

/** The form's own name for each rule, so the report and the field agree. */
const RULE_LABELS: Record<RuleOutcome["rule"], string> = {
  login_url_pattern: "Ends up at the login page",
  success_pattern: "Page must contain",
  failure_pattern: "Page must not contain",
};

/**
 * What one rule did, in a sentence.
 *
 * Worded per rule because matching means the opposite thing depending on which it is: a success
 * pattern is supposed to be on the signed-in page, the other two on the signed-out one.
 */
function ruleNote(rule: RuleOutcome): string {
  if (rule.helps) return "works — matches only the page it is meant to";
  if (!rule.on_live && !rule.on_dead) return "never matched either page, so it does nothing";
  if (rule.on_live && rule.on_dead) return "matches both pages, so it cannot tell them apart";
  return rule.rule === "success_pattern"
    ? "matches the signed-out page instead, so it has this backwards"
    : "matches the signed-in page instead, so it would report a working session as dead";
}

function Outcome({
  label,
  outcome,
  detail,
  good,
}: {
  label: string;
  outcome: string;
  detail?: string | null;
  good: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-muted">{label}</dt>
      <dd className={good ? "text-alive" : "text-risk"}>
        {statusWord(outcome)}
        {detail ? <span className="text-muted"> — {detail}</span> : null}
      </dd>
    </div>
  );
}

/** A check outcome as the interface words it elsewhere. */
function statusWord(outcome: string): string {
  return outcome.replaceAll("_", " ");
}

function Advanced({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <fieldset className="grid gap-4 sm:grid-cols-2">
      <Field
        label="Login URL"
        hint="Where the browser opens to log in, and — when it differs from the ping URL — what a check treats as landing on the login page. Filled in by the comparison; the ping URL is used if it is empty."
      >
        <Input
          type="url"
          value={draft.login_url ?? ""}
          onChange={(event) => set("login_url", text(event.target.value))}
          placeholder="e.g. https://example.org/login"
          {...notACredential}
        />
      </Field>
      <Field
        label="Ends up at a URL like"
        hint="Only for a site that sends a signed-out request somewhere other than the page you log in on. Empty means the login URL above is used."
      >
        <Input
          value={draft.login_url_pattern ?? ""}
          onChange={(event) => set("login_url_pattern", text(event.target.value))}
          placeholder="e.g. session-expired"
          {...notACredential}
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
          {...notACredential}
        />
      </Field>
      <div className="sm:col-span-2">
        <Toggle
          checked={draft.follow_redirects}
          onChange={(value) => set("follow_redirects", value)}
          label="Follow redirects"
          hint="Off if the site answers with a redirect when the session is fine."
        />
      </div>
    </fieldset>
  );
}

/**
 * How many things a check could tell a dead session by.
 *
 * The login URL counts, since a check derives the login-page rule from it — but only when it
 * differs from the pinged page, which is exactly when that rule can fire.
 */
function countSignals(draft: SiteWrite): number {
  const explicit = [draft.success_pattern, draft.failure_pattern, draft.login_url_pattern].filter(
    Boolean,
  ).length;
  return explicit + (redirectsElsewhere(draft) ? 1 : 0);
}

function redirectsElsewhere(draft: SiteWrite): boolean {
  if (!draft.login_url) return false;
  try {
    return new URL(draft.login_url).pathname !== new URL(draft.ping_url).pathname;
  } catch {
    // A URL still being typed is not a signal either way.
    return false;
  }
}

/**
 * Whether an existing site is being watched for a dead session.
 *
 * Anything set means yes. Nothing set means the site currently notices nothing, which is what its
 * owner asked for by saving it that way — guessing otherwise overrode a deliberate choice every
 * time the form was reopened.
 */
function watchingFor(site: Site | null): Watching {
  if (site === null) return "no";
  return countSignals(toWrite(site)) > 0 ? "yes" : "no";
}
