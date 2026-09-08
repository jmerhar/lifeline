/**
 * The main screen: every site, its state, and what to do about it.
 *
 * A table rather than cards. The whole point is comparing one row against another — which
 * of these is about to lapse — and cards put every row on its own island.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { toWrite, type Site, type SiteWrite } from "../api/types";
import { PulseStrip } from "../components/PulseStrip";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Card, Empty, Problem, Spinner, Switch } from "../components/ui";
import { countdown, relativeTime, summarise, timestamp } from "../lib/format";
import { SessionPanel } from "./SessionPanel";
import { SiteForm, type Approach, type Tab } from "./SiteForm";

export function Sites() {
  const client = useQueryClient();
  const sites = useQuery({ queryKey: ["sites"], queryFn: api.sites });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });

  const [editing, setEditing] = useState<Site | null | undefined>(undefined);
  const [editingTab, setEditingTab] = useState<Tab>("site");
  const [editingApproach, setEditingApproach] = useState<Approach | undefined>(undefined);
  const [loggingInto, setLoggingInto] = useState<Site | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Separate from saveError, which is rendered inside the form: an action taken from the list
  // itself has no form open to report into.
  const [listError, setListError] = useState<string | null>(null);

  const refresh = () => client.invalidateQueries({ queryKey: ["sites"] });

  /** Open the editor on a site, on a given panel, optionally forcing a detection approach. */
  const edit = (site: Site, tab: Tab = "site", approach?: Approach) => {
    setEditingTab(tab);
    setEditingApproach(approach);
    setEditing(site);
  };

  const save = useMutation({
    mutationFn: (payload: SiteWrite) =>
      editing ? api.updateSite(editing.id, payload) : api.createSite(payload),
    onSuccess: async (saved, _payload, context) => {
      setSaveError(null);
      setEditing(undefined);
      await refresh();
      // A new site continues into the login rather than stopping here: the one question the add
      // form does not ask cannot be answered until someone has seen the site logged in.
      if (context === undefined) setLoggingInto(saved);
    },
    // The site being edited at the moment the request goes out, so the handler above can tell an
    // update from a creation without reading state that has since been cleared.
    onMutate: () => editing ?? undefined,
    onError: (cause) =>
      setSaveError(cause instanceof ApiError ? cause.message : "The site could not be saved."),
  });

  const check = useMutation({ mutationFn: api.checkNow, onSuccess: refresh });
  // Pausing a site is a one-click decision made while looking at the list, not a reason to open
  // a form. Sent as a whole site because that is what the API accepts.
  const setEnabled = useMutation({
    mutationFn: ({ site, enabled }: { site: Site; enabled: boolean }) =>
      api.updateSite(site.id, { ...toWrite(site), enabled }),
    onSuccess: refresh,
    // Cleared as the request goes out, not after it settles — settling includes failing, which
    // would wipe the message the failure just set.
    onMutate: () => setListError(null),
    onError: () => setListError("The site could not be paused."),
  });
  const remove = useMutation({ mutationFn: api.deleteSite, onSuccess: refresh });

  if (sites.isPending) return <Spinner label="Loading sites…" />;
  if (sites.isError) return <Problem>Sites could not be loaded.</Problem>;

  const rows = sites.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-small text-muted tabular">{summarise(rows.map((site) => site.status))}</p>
        <Button tone="primary" onClick={() => setEditing(null)}>
          <Plus className="h-4 w-4" />
          Add site
        </Button>
      </div>

      {listError ? <Problem>{listError}</Problem> : null}

      <Card>
        {rows.length === 0 ? (
          <Empty
            title="No sites yet. Add the first site you want to keep alive."
            action={
              <Button tone="primary" onClick={() => setEditing(null)}>
                <Plus className="h-4 w-4" />
                Add site
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[880px] border-collapse text-small">
              <thead>
                <tr className="border-b border-line text-left text-micro text-muted">
                  <th className="px-3 py-2 font-medium">On</th>
                  <th className="px-3 py-2 font-medium">Site</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Pulse</th>
                  <th className="px-3 py-2 font-medium">Checked</th>
                  <th className="px-3 py-2 font-medium">Lapses in</th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((site) => (
                  <SiteRow
                    key={site.id}
                    site={site}
                    expanded={expanded === site.id}
                    onToggle={() => setExpanded(expanded === site.id ? null : site.id)}
                    onEdit={() => edit(site)}
                    onLogin={() => setLoggingInto(site)}
                    onCheck={() => check.mutate(site.id)}
                    checking={check.isPending && check.variables === site.id}
                    onEnabled={(enabled) => setEnabled.mutate({ site, enabled })}
                    switching={setEnabled.isPending && setEnabled.variables?.site.id === site.id}
                    onDelete={() => {
                      if (
                        window.confirm(
                          `Delete ${site.name}? Its stored session and history go too.`,
                        )
                      ) {
                        remove.mutate(site.id);
                      }
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {editing !== undefined ? (
        <SiteForm
          site={editing}
          defaultIntervalDays={settings.data?.default_interval_days ?? 7}
          initialTab={editingTab}
          initialApproach={editingApproach}
          error={saveError}
          busy={save.isPending}
          onCancel={() => {
            setEditing(undefined);
            setSaveError(null);
          }}
          onSave={(payload) => save.mutate(payload)}
        />
      ) : null}

      {loggingInto ? (
        <SessionPanel
          site={loggingInto}
          onClose={() => setLoggingInto(null)}
          onSaved={async () => {
            const site = loggingInto;
            setLoggingInto(null);
            await refresh();
            // Straight to the panel the login has just made answerable, with the fresh session
            // attached so the comparison is offered rather than explained away.
            const saved = (await api.sites()).find((row) => row.id === site.id);
            // The comparison is selected because a login has just happened, which is the one
            // moment it is both possible and the reason someone is here.
            if (saved) edit(saved, "detection", "detect");
          }}
        />
      ) : null}
    </div>
  );
}

function SiteRow({
  site,
  expanded,
  onToggle,
  onEdit,
  onLogin,
  onCheck,
  onDelete,
  onEnabled,
  checking,
  switching,
}: {
  site: Site;
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onLogin: () => void;
  onCheck: () => void;
  onDelete: () => void;
  onEnabled: (enabled: boolean) => void;
  checking: boolean;
  switching: boolean;
}) {
  return (
    <>
      <tr className={`border-b border-line/60 ${site.enabled ? "" : "opacity-60"}`}>
        <td className="px-3 py-2">
          <Switch
            checked={site.enabled}
            onChange={onEnabled}
            busy={switching}
            label={site.enabled ? `Pause ${site.name}` : `Resume ${site.name}`}
          />
        </td>
        <td className="px-3 py-2">
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            // Named for what it does, rather than leaving the accessible name to be the site
            // name and host read out together.
            aria-label={`Show details for ${site.name}`}
            className="flex items-center gap-2 text-left hover:text-accent"
          >
            {site.favicon ? (
              <img src={site.favicon} alt="" className="h-4 w-4 rounded-sm" />
            ) : (
              <span aria-hidden="true" className="h-4 w-4 rounded-sm border border-line" />
            )}
            <span>
              <span className="block">{site.name}</span>
              <span className="block font-mono text-micro text-muted">{hostOf(site.ping_url)}</span>
            </span>
          </button>
        </td>
        <td className="px-3 py-2">
          <StatusBadge status={site.status} />
          {/* A status word on its own leaves someone reading "due soon" with no way to find out
              what is due, so the reason travels with it. */}
          {site.risk ? (
            <span className="mt-0.5 block max-w-[22rem] text-micro text-muted">{site.risk}</span>
          ) : null}
        </td>
        <td className="px-3 py-2">
          {/* The schema marks pulse optional because the field has a default, so it is
              treated as possibly absent rather than assumed. */}
          <PulseStrip pulse={(site.pulse ?? []).map((outcome) => ({ outcome }))} />
        </td>
        <td className="px-3 py-2 tabular text-muted">{relativeTime(site.last_check_at)}</td>
        <td className="px-3 py-2 tabular text-muted">{countdown(site.deadline_at)}</td>
        <td className="px-3 py-2">
          <div className="flex items-center justify-end gap-1">
            <IconButton label="Check now" onClick={onCheck} disabled={checking}>
              <RefreshCw className={`h-4 w-4 ${checking ? "animate-spin" : ""}`} />
            </IconButton>
            <IconButton label={`Log in to ${site.name}`} onClick={onLogin}>
              <KeyRound className="h-4 w-4" />
            </IconButton>
            <IconButton label={`Edit ${site.name}`} onClick={onEdit}>
              <Pencil className="h-4 w-4" />
            </IconButton>
            <IconButton label={`Delete ${site.name}`} onClick={onDelete}>
              <Trash2 className="h-4 w-4" />
            </IconButton>
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-line/60 bg-raised/40">
          <td colSpan={7} className="px-3 py-3">
            <dl className="grid gap-x-6 gap-y-2 text-micro sm:grid-cols-3">
              <Detail label="Ping URL">
                <span className="font-mono break-all">{site.ping_url}</span>
              </Detail>
              <Detail label="Next check">{timestamp(site.next_check_at)}</Detail>
              <Detail label="Last success">{timestamp(site.last_ok_at)}</Detail>
              <Detail label="Session">
                {site.session
                  ? `${site.session.cookie_names.length} cookie(s), captured ${relativeTime(
                      site.session.captured_at,
                    )} (${site.session.captured_via})`
                  : "none — log in to capture one"}
              </Detail>
              <Detail label="Everything expires">
                {site.session ? timestamp(site.session.expires_at) : "—"}
              </Detail>
              <Detail label="Checked every">
                {site.interval_days} {site.interval_days === 1 ? "day" : "days"}
                {site.enabled ? "" : " (paused)"}
              </Detail>
              {site.notes ? (
                <div className="sm:col-span-3">
                  <Detail label="Notes">{site.notes}</Detail>
                </div>
              ) : null}
            </dl>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="rounded p-1.5 text-muted hover:bg-raised hover:text-ink disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    // A malformed URL should still show something rather than blanking the cell.
    return url;
  }
}
