/**
 * The version running, and the commit its image was built from, which says exactly what is
 * installed when that is a build of the main branch rather than a release.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

/** Where a commit of the app's source can be read. */
const COMMITS = "https://github.com/jmerhar/lifeline/commit/";

export function Footer() {
  // Without an answer the footer stays empty; the page itself reports a server it cannot reach.
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
  if (!health.data) return null;
  const { version, revision } = health.data;
  return (
    <footer className="mx-auto max-w-[1200px] px-4 pb-6 text-small text-muted">
      lifeline {version}
      {revision && (
        <>
          {" · "}
          <a className="hover:text-ink" href={COMMITS + revision}>
            {revision.slice(0, 7)}
          </a>
        </>
      )}
    </footer>
  );
}
