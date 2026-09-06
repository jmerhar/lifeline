/**
 * A site's recent checks, drawn as a heartbeat trace.
 *
 * Direction carries the meaning, not just colour: a successful check deflects up from the
 * baseline and a failure deflects down. Colour alone would leave the strip unreadable to a
 * red-green colourblind reader — and this strip is the fastest way to see that something
 * has been failing for a while, so it has to survive being seen in grey.
 *
 * Each tick is titled with what it was and when, which is where the detail lives; twelve
 * ticks in a table row have no space for labels.
 */

import type { CheckOutcome } from "../api/types";
import { isGood, outcomeLabels } from "../lib/format";

export interface PulseTick {
  outcome: CheckOutcome;
  at?: string;
}

const TICKS = 12;
// A 3px mark with a 1px gap keeps twelve of them inside the ~120px the column allows while
// leaving each one wide enough to see.
const TICK_WIDTH = 3;
const TICK_GAP = 1;
const HEIGHT = 18;
const BASELINE = HEIGHT / 2;
const DEFLECTION = 6;

export function PulseStrip({ pulse, className = "" }: { pulse: PulseTick[]; className?: string }) {
  // Padded from the left so the newest check is always at the right-hand edge; a site with
  // three checks and a site with twelve then line up down the column.
  const padding = Math.max(TICKS - pulse.length, 0);
  const width = TICKS * (TICK_WIDTH + TICK_GAP) - TICK_GAP;

  return (
    <svg
      width={width}
      height={HEIGHT}
      viewBox={`0 0 ${width} ${HEIGHT}`}
      className={className}
      role="img"
      aria-label={ariaLabel(pulse)}
    >
      {/* The baseline is what makes a downward deflection legible as "below the line". */}
      <line
        x1={0}
        y1={BASELINE}
        x2={width}
        y2={BASELINE}
        stroke="rgb(var(--line))"
        strokeWidth={1}
      />
      {Array.from({ length: TICKS }, (_, index) => {
        const tick = index >= padding ? pulse[index - padding] : undefined;
        const x = index * (TICK_WIDTH + TICK_GAP);
        if (!tick) {
          return (
            <rect
              key={index}
              x={x}
              y={BASELINE - 0.5}
              width={TICK_WIDTH}
              height={1}
              fill="rgb(var(--unknown))"
              opacity={0.5}
            />
          );
        }
        const good = isGood(tick.outcome);
        return (
          <rect
            key={index}
            x={x}
            y={good ? BASELINE - DEFLECTION : BASELINE}
            width={TICK_WIDTH}
            height={DEFLECTION}
            rx={1}
            fill={good ? "rgb(var(--alive))" : "rgb(var(--lapsed))"}
          >
            <title>{`${outcomeLabels[tick.outcome]}${tick.at ? ` · ${tick.at}` : ""}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function ariaLabel(pulse: PulseTick[]): string {
  if (pulse.length === 0) return "No checks yet";
  const failures = pulse.filter((tick) => !isGood(tick.outcome)).length;
  const checks = `${pulse.length} recent ${pulse.length === 1 ? "check" : "checks"}`;
  return failures === 0 ? `${checks}, all ok` : `${checks}, ${failures} failed`;
}
