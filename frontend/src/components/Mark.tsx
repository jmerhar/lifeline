/**
 * The lifeline mark: a single heartbeat.
 *
 * Four strokes, so it survives being drawn at 16 pixels, and it is the same shape as the
 * pulse strip in the site list — the mark and the product's central piece of information
 * are the same idea drawn at two sizes.
 */
export function Mark({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M1.5 12h5.5l2-8 3 13 2-5h8.5" />
    </svg>
  );
}

/** The mark and the name, as used in the header and above the setup wizard. */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <Mark className="h-5 w-5 text-alive" />
      <span className="text-lead font-medium tracking-[-0.01em] lowercase">lifeline</span>
    </span>
  );
}
