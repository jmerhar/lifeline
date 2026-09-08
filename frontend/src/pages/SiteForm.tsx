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
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { emptySite, toWrite, type DetectedRules, type Site, type SiteWrite } from "../api/types";
import { Modal } from "../components/Modal";
import {
  Button,
  Choice,
  Field,
  Input,
  notACredential,
  Problem,
  Select,
  TextArea,
  Toggle,
} from "../components/ui";

/** How the detection rules are being arrived at. */
export type Approach = "detect" | "manual" | "none";

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
  initialApproach,
  onCancel,
  onSave,
  error,
  busy,
}: {
  site: Site | null;
  defaultIntervalDays: number;
  /** Which panel to open on. The login flow lands on detection, having just made it answerable. */
  initialTab?: Tab;
  /** Overrides what the site's own settings imply — the login flow asks for the comparison. */
  initialApproach?: Approach;
  onCancel: () => void;
  onSave: (payload: SiteWrite) => void;
  error?: string | null;
  busy?: boolean;
}) {
  const [draft, setDraft] = useState<SiteWrite>(() =>
    site ? toWrite(site) : { ...emptySite, interval_days: defaultIntervalDays },
  );
  const [tab, setTab] = useState<Tab>(initialTab);
  const [approach, setApproach] = useState<Approach>(
    () => initialApproach ?? approachFor(site),
  );
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
        // Where a signed-out request landed is the login page, so it answers where to open a
        // browser next time as well as what the page looks like.
        login_url: rules.login_url ?? current.login_url,
        login_url_pattern: rules.login_url_pattern ?? null,
        success_pattern: rules.success_pattern ?? null,
        failure_pattern: rules.failure_pattern ?? null,
      }));
    },
    onError: (cause) =>
      setDetectError(cause instanceof ApiError ? cause.message : "The site could not be compared."),
  });

  const isNew = site === null;
  const hasSession = site?.session != null;
  const ruleCount = [draft.login_url_pattern, draft.success_pattern, draft.failure_pattern].filter(
    Boolean,
  ).length;
  // Choosing to detect and then setting nothing leaves a site configured to notice nothing while
  // looking configured. Choosing not to detect is a real answer and is never blocked. Neither
  // applies while adding, where the question has not been asked yet.
  const blocked = !isNew && approach !== "none" && ruleCount === 0;

  const submit = () =>
    onSave(
      approach === "none"
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
            title={blocked ? "Give it a rule, or choose not to detect a dead session" : undefined}
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
              What the site is. Saving opens a browser so you can log in — after that lifeline can
              work out how to tell a live session from a dead one by itself.
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
                approach={approach}
                onApproach={setApproach}
                hasSession={hasSession}
                found={found}
                detecting={detect.isPending}
                onDetect={() => detect.mutate()}
                detectError={detectError}
                ruleCount={ruleCount}
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
  approach,
  onApproach,
  hasSession,
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
        <Toggle
          checked={draft.follow_redirects}
          onChange={(value) => set("follow_redirects", value)}
          label="Follow redirects"
          hint="Off if the site answers with a redirect when the session is fine."
        />
      </fieldset>
    </div>
  );
}

function Advanced({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <fieldset className="grid gap-4 sm:grid-cols-2">
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
    </fieldset>
  );
}

function Rules({ draft, set, text }: { draft: SiteWrite; set: Setter; text: Text }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field
        label="Login URL"
        hint="Optional. Where the browser opens to log in. The ping URL is used if it is empty, which is usually enough — a site with no session sends you to its login page."
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
        label="Login page looks like"
        hint="Text or a regex matched against the URL the request ends on."
      >
        <Input
          value={draft.login_url_pattern ?? ""}
          onChange={(event) => set("login_url_pattern", text(event.target.value))}
          placeholder="e.g. login.php"
          {...notACredential}
        />
      </Field>
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
          // credential, which makes a password manager both fill it in and offer to save a login
          // for the whole form. "Remember me" belongs to a login page just as reliably.
          placeholder="e.g. Remember me"
          {...notACredential}
        />
      </Field>
    </div>
  );
}

/**
 * Which approach an existing site's settings represent.
 *
 * No rules means "don't detect", because that is what the site does and, having been saved that
 * way, is what its owner asked for. Guessing "you must have meant to compare" from the presence
 * of a session silently overrode a deliberate choice every time the form was reopened.
 *
 * Arriving straight from a login is the one case where the comparison should start selected, and
 * that is knowable from the way the panel was opened rather than from the row — so the caller
 * says so with ``initialApproach``.
 */
function approachFor(site: Site | null): Approach {
  if (site === null) return "none";
  const set = [site.login_url_pattern, site.success_pattern, site.failure_pattern].filter(Boolean);
  return set.length > 0 ? "manual" : "none";
}
