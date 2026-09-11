/**
 * The instance settings.
 *
 * Notification destinations come first because they are the part that has to be right: if
 * nothing is configured here, a session can lapse without anyone hearing about it — which
 * is the one failure this tool exists to prevent.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import type { Settings as SettingsPayload } from "../api/types";
import {
  Button,
  Card,
  type ControlProps,
  Field,
  Input,
  Problem,
  Select,
  Spinner,
  TextArea,
  Toggle,
} from "../components/ui";
import { acceptLanguage, LANGUAGES, languageTag } from "../lib/languages";

export function Settings() {
  const client = useQueryClient();
  const query = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  // Edits live in their own state, falling back to what was loaded. Deriving it this way
  // rather than copying the response into state on every change means there is no moment
  // where the form is mounted with nothing in it.
  const [edited, setEdited] = useState<SettingsPayload | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const draft = edited ?? query.data ?? null;

  const save = useMutation({
    mutationFn: (payload: SettingsPayload) => api.saveSettings(payload),
    onSuccess: async (saved) => {
      setEdited(saved);
      setNote("Settings saved.");
      setError(null);
      await client.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (cause) =>
      setError(cause instanceof ApiError ? cause.message : "The settings could not be saved."),
  });

  const test = useMutation({
    mutationFn: api.testNotification,
    onSuccess: (result) => {
      setNote(result.detail);
      setError(null);
    },
    onError: () => setError("The test notification could not be sent."),
  });

  if (query.isPending) return <Spinner label="Loading settings…" />;
  if (!draft) return <Problem>Settings could not be loaded.</Problem>;

  const set = <K extends keyof SettingsPayload>(key: K, value: SettingsPayload[K]) =>
    setEdited({ ...draft, [key]: value });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(draft);
      }}
    >
      <Card className="flex flex-col gap-4 p-4">
        <h2 className="text-lead font-medium">Notifications</h2>
        <Field
          label="Where to send them"
          hint="One Apprise URL per line — for example tgram://token/chat-id or mailto://user:password@smtp.example.org. Lines starting with # are ignored."
        >
          <TextArea
            rows={4}
            value={draft.apprise_urls}
            onChange={(event) => set("apprise_urls", event.target.value)}
            spellCheck={false}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Toggle
            checked={draft.notify_on_lapsed}
            onChange={(value) => set("notify_on_lapsed", value)}
            label="A session stopped working"
            hint="The one you want."
          />
          <Toggle
            checked={draft.notify_on_recovered}
            onChange={(value) => set("notify_on_recovered", value)}
            label="A session started working again"
          />
          <Toggle
            checked={draft.notify_on_errors}
            onChange={(value) => set("notify_on_errors", value)}
            label="A site keeps failing to answer"
          />
          <Toggle
            checked={draft.notify_on_deadline}
            onChange={(value) => set("notify_on_deadline", value)}
            label="An account is running out of time"
          />
          <Toggle
            checked={draft.notify_on_cookie_expiry}
            onChange={(value) => set("notify_on_cookie_expiry", value)}
            label="A stored cookie is about to expire"
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Warn this far ahead" hint="Days.">
            <Input
              type="number"
              min={0}
              max={365}
              value={draft.warning_lead_days}
              onChange={(event) => set("warning_lead_days", Number(event.target.value))}
            />
          </Field>
          <Field label="Stay quiet for" hint="Hours between repeats about the same site.">
            <Input
              type="number"
              min={0}
              max={8760}
              value={draft.notify_cooldown_hours}
              onChange={(event) => set("notify_cooldown_hours", Number(event.target.value))}
            />
          </Field>
          <Field label="Report failures after" hint="Consecutive failed checks.">
            <Input
              type="number"
              min={1}
              max={100}
              value={draft.error_threshold}
              onChange={(event) => set("error_threshold", Number(event.target.value))}
            />
          </Field>
        </div>
        <div>
          <Button type="button" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? "Sending…" : "Send a test notification"}
          </Button>
        </div>
      </Card>

      <Card className="flex flex-col gap-4 p-4">
        <h2 className="text-lead font-medium">Checking</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Default interval" hint="Days, for a newly added site.">
            <Input
              type="number"
              min={1}
              max={365}
              value={draft.default_interval_days}
              onChange={(event) => set("default_interval_days", Number(event.target.value))}
            />
          </Field>
          <Field label="Keep history for" hint="Days. 0 keeps everything.">
            <Input
              type="number"
              min={0}
              max={3650}
              value={draft.retention_days}
              onChange={(event) => set("retention_days", Number(event.target.value))}
            />
          </Field>
          <Field label="Close an idle login after" hint="Minutes.">
            <Input
              type="number"
              min={1}
              max={240}
              value={draft.browser_idle_timeout_minutes}
              onChange={(event) =>
                set("browser_idle_timeout_minutes", Number(event.target.value))
              }
            />
          </Field>
          <Field
            label="Answer in this language"
            hint="Asked for on every check. A site serving more than one language decides from this, and patterns typed from a page in one language will not match another. Something else lets you write the Accept-Language header yourself."
          >
            <LanguageChoice
              value={draft.accept_language}
              onChange={(header) => set("accept_language", header)}
            />
          </Field>
          <Field
            label="Log detail"
            hint="Takes effect at once. Written to logs/lifeline.log beside the database, and to the container's output."
          >
            <Select
              value={draft.log_level}
              onChange={(event) =>
                set("log_level", event.target.value as SettingsPayload["log_level"])
              }
            >
              <option value="DEBUG">Debug — also why each check decided what it did</option>
              <option value="INFO">Info — every request, check and change of state</option>
              <option value="WARNING">Warning — only what needs attention</option>
              <option value="ERROR">Error — only failures</option>
            </Select>
          </Field>
        </div>
      </Card>

      {error ? <Problem>{error}</Problem> : null}
      {note && !error ? (
        <p role="status" className="text-small text-alive">
          {note}
        </p>
      ) : null}

      <div className="flex justify-end">
        <Button tone="primary" type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save settings"}
        </Button>
      </div>
    </form>
  );
}

/** The option standing for a header this list cannot offer. */
const OWN_HEADER = "own";

/**
 * Which language to ask sites for, chosen by name.
 *
 * What is stored is the Accept-Language header itself, because that is what a check sends and
 * because a header can express preferences no list of single languages can — a fallback chain,
 * or a weighting of its own. So the list is the ordinary way in, and choosing to write the
 * header keeps the box for it.
 */
function LanguageChoice({
  value,
  onChange,
  ...control
}: {
  value: string;
  onChange: (header: string) => void;
} & ControlProps) {
  // Whether the box is showing belongs to this field. A header no language accounts for has to
  // show it, and someone who asked for it keeps it until they choose a language again — which a
  // value derived from the header alone would take away the moment what they typed happened to
  // match a listed language.
  const [own, setOwn] = useState(() => languageTag(value) === null);

  return (
    <div className="flex flex-col gap-1.5">
      <Select
        {...control}
        value={own ? OWN_HEADER : languageTag(value)!}
        onChange={(event) => {
          const chosen = event.target.value;
          setOwn(chosen === OWN_HEADER);
          // Choosing to write the header leaves the current one to be edited rather than
          // emptying the box: it is the nearest thing to what was asked for.
          if (chosen !== OWN_HEADER) onChange(acceptLanguage(chosen));
        }}
      >
        {LANGUAGES.map((language) => (
          <option key={language.tag} value={language.tag}>
            {language.label}
          </option>
        ))}
        <option value={OWN_HEADER}>Something else…</option>
      </Select>
      {own ? (
        <Input
          aria-label="Accept-Language header"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="en-US,en;q=0.9"
          spellCheck={false}
        />
      ) : null}
    </div>
  );
}
