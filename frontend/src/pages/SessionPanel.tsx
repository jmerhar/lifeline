/**
 * Giving a site a session: through a real browser, or by pasting cookies.
 *
 * Two routes because they fail in opposite ways. The browser handles two-factor prompts,
 * consent walls and bot challenges, but needs one to be running here; pasting works from
 * whatever browser you are already logged in with and needs nothing.
 */

import { useEffect, useState } from "react";

import { api, ApiError } from "../api/client";
import type { LoginSession, Site } from "../api/types";
import { Modal } from "../components/Modal";
import { VncScreen } from "../components/VncScreen";
import { Button, Field, Problem, TextArea } from "../components/ui";

type Tab = "browser" | "paste";

export function SessionPanel({
  site,
  onClose,
  onSaved,
}: {
  site: Site;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [tab, setTab] = useState<Tab>("browser");

  return (
    <Modal
      title={`Log in to ${site.name}`}
      onClose={onClose}
      wide={tab === "browser"}
      footer={null}
    >
      <div className="mb-4 flex gap-1 border-b border-line">
        <TabButton active={tab === "browser"} onClick={() => setTab("browser")}>
          Use a browser
        </TabButton>
        <TabButton active={tab === "paste"} onClick={() => setTab("paste")}>
          Paste cookies
        </TabButton>
      </div>
      {tab === "browser" ? (
        <BrowserTab site={site} onClose={onClose} onSaved={onSaved} />
      ) : (
        <PasteTab site={site} onSaved={onSaved} />
      )}
    </Modal>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "true" : undefined}
      className={`-mb-px border-b-2 px-3 py-2 text-small ${
        active ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

function BrowserTab({
  site,
  onClose,
  onSaved,
}: {
  site: Site;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [session, setSession] = useState<LoginSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let abandoned = false;
    let token: string | null = null;

    api
      .openLogin(site.id)
      .then((opened) => {
        if (abandoned) {
          // The panel closed while the browser was starting; nothing is watching it, so it
          // has to be shut down or it holds an X server until its idle timeout.
          void api.closeLogin(tokenOf(opened));
          return;
        }
        token = tokenOf(opened);
        setSession(opened);
      })
      .catch((cause) => {
        if (!abandoned) {
          setError(
            cause instanceof ApiError ? cause.message : "The browser could not be started.",
          );
        }
      });

    return () => {
      abandoned = true;
      if (token) void api.closeLogin(token);
    };
  }, [site.id]);

  async function save() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveLogin(tokenOf(session));
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "The session could not be saved.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-small text-muted">
        Log in as you normally would, then save the session. Two-factor prompts and bot checks
        all work here — it is a real browser.
      </p>
      {error ? <Problem>{error}</Problem> : null}
      {session ? (
        <VncScreen
          path={session.ws_path}
          className="aspect-[16/10] w-full overflow-hidden rounded border border-line"
        />
      ) : (
        <div className="flex aspect-[16/10] w-full items-center justify-center rounded border border-line bg-base text-small text-muted">
          {error ? "Nothing to show." : "Starting a browser…"}
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" onClick={onClose}>
          Cancel
        </Button>
        <Button tone="primary" type="button" onClick={save} disabled={!session || busy}>
          {busy ? "Saving…" : "Save session"}
        </Button>
      </div>
    </div>
  );
}

function PasteTab({ site, onSaved }: { site: Site; onSaved: () => void }) {
  const [text, setText] = useState("");
  const [userAgent, setUserAgent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.importSession(site.id, { text, user_agent: userAgent.trim() || null });
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Those cookies could not be read.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <Field
        label="Cookies"
        hint="A Cookie header, a JSON export from a cookie extension, or a cookies.txt file."
      >
        <TextArea
          rows={8}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="session=…; uid=…"
          required
          autoFocus
        />
      </Field>
      <Field
        label="User-Agent"
        hint="Paste the one from the browser you copied the cookies out of. Some sites tie the session to it."
      >
        <TextArea
          rows={2}
          value={userAgent}
          onChange={(event) => setUserAgent(event.target.value)}
          placeholder="Mozilla/5.0 …"
        />
      </Field>
      {error ? <Problem>{error}</Problem> : null}
      <div className="flex justify-end">
        <Button tone="primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save session"}
        </Button>
      </div>
    </form>
  );
}

/** The token the API addresses a live login session by. */
function tokenOf(session: LoginSession): string {
  // ws_path is /api/browser/<token>/ws.
  return session.ws_path.split("/")[3] ?? "";
}
