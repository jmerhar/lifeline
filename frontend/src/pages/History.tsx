/** Every recent check, newest first. */

import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Site } from "../api/types";
import { Card, Empty, Problem, Spinner } from "../components/ui";
import { isGood, outcomeLabels, timestamp } from "../lib/format";

export function History() {
  const checks = useQuery({ queryKey: ["checks"], queryFn: () => api.checks(200) });
  const sites = useQuery({ queryKey: ["sites"], queryFn: api.sites });

  if (checks.isPending || sites.isPending) return <Spinner label="Loading history…" />;
  if (checks.isError) return <Problem>The history could not be loaded.</Problem>;

  const names = new Map((sites.data ?? []).map((site: Site) => [site.id, site.name]));
  const rows = checks.data ?? [];

  return (
    <Card>
      {rows.length === 0 ? (
        <Empty title="No checks yet. They will appear here as sites are pinged." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-small">
            <thead>
              <tr className="border-b border-line text-left text-micro text-muted">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Site</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Took</th>
                <th className="px-3 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((check) => (
                <tr key={check.id} className="border-b border-line/60 align-top">
                  <td className="whitespace-nowrap px-3 py-2 tabular text-muted">
                    {timestamp(check.started_at)}
                  </td>
                  <td className="px-3 py-2">{names.get(check.site_id) ?? `site ${check.site_id}`}</td>
                  <td className="px-3 py-2">
                    <span className={isGood(check.outcome) ? "text-alive" : "text-lapsed"}>
                      {isGood(check.outcome) ? "●" : "✕"} {outcomeLabels[check.outcome]}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular text-muted">{check.status_code ?? "—"}</td>
                  <td className="px-3 py-2 tabular text-muted">
                    {check.duration_ms === null ? "—" : `${check.duration_ms} ms`}
                  </td>
                  <td className="px-3 py-2 text-micro text-muted">{check.detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
