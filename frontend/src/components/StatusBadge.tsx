/**
 * A site's state, as a shape and a word.
 *
 * Never colour on its own: the glyph differs per state as well as the hue, so the column is
 * readable in grey, in a screenshot, and to a colourblind reader.
 */

import type { SiteStatus } from "../api/types";
import { statusColors, statusLabels } from "../lib/format";

const glyphs: Record<SiteStatus, string> = {
  unknown: "○",
  alive: "●",
  at_risk: "▲",
  lapsed: "✕",
  error: "!",
};

export function StatusBadge({ status }: { status: SiteStatus }) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${statusColors[status]}`}>
      <span aria-hidden="true" className="text-micro leading-none">
        {glyphs[status]}
      </span>
      <span className="text-small">{statusLabels[status]}</span>
    </span>
  );
}
