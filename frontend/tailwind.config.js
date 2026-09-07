/**
 * Tailwind is pointed at CSS custom properties rather than literal colours, so the light
 * and dark palettes are two sets of values in one place (src/index.css) instead of a
 * `dark:` variant on every element. Each theme's colours are chosen against that theme's
 * background rather than derived from the other by inversion.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Named canvas, not base: `text-` is one namespace for both colours and font
        // sizes, so a colour called "base" makes `text-base` mean the body font size AND
        // the page background colour. Tailwind emits both, the colour wins, and every
        // element without an explicit colour is painted the same shade as its background.
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        accent: "rgb(var(--accent) / <alpha-value>)",
        "accent-ink": "rgb(var(--accent-ink) / <alpha-value>)",
        alive: "rgb(var(--alive) / <alpha-value>)",
        risk: "rgb(var(--risk) / <alpha-value>)",
        lapsed: "rgb(var(--lapsed) / <alpha-value>)",
        unknown: "rgb(var(--unknown) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        // A five-step scale, used as-is. Data-dense screens go wrong when every heading
        // invents its own size.
        micro: ["0.75rem", { lineHeight: "1rem" }],
        small: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.5rem" }],
        lead: ["1rem", { lineHeight: "1.5rem" }],
        title: ["1.25rem", { lineHeight: "1.75rem" }],
        display: ["1.75rem", { lineHeight: "2.25rem" }],
      },
      borderRadius: {
        DEFAULT: "0.375rem",
      },
    },
  },
  plugins: [],
};
