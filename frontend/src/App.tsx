/**
 * What the app shows, and which of three states it is in.
 *
 * The instance can be unconfigured, logged out, or in use, and the difference is decided by
 * the API rather than guessed at here: a request answers "setup required", "not
 * authenticated", or the data. That keeps the three cases from drifting apart, which is how
 * an app ends up showing a login form nobody can get past.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { api, NotAuthenticated, SetupRequired } from "./api/client";
import { TopNav } from "./components/TopNav";
import { Spinner } from "./components/ui";
import { useTheme } from "./hooks/useTheme";
import { History } from "./pages/History";
import { Login } from "./pages/Login";
import { Settings } from "./pages/Settings";
import { Setup } from "./pages/Setup";
import { Sites } from "./pages/Sites";

type Gate =
  | { state: "loading" }
  | { state: "setup"; tokenRequired: boolean }
  | { state: "login" }
  | { state: "ready" };

export function App() {
  const client = useQueryClient();
  const { theme, toggle } = useTheme();

  const session = useQuery({
    queryKey: ["session"],
    queryFn: api.me,
    // Both are answers, not failures: retrying would delay showing the right screen.
    retry: false,
  });

  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: api.setupState,
    enabled: session.error instanceof SetupRequired,
    retry: false,
  });

  const gate = resolve(session, setup);

  if (gate.state === "loading") return <Spinner label="Starting…" />;

  if (gate.state === "setup") {
    return (
      <Setup
        tokenRequired={gate.tokenRequired}
        onDone={() => client.invalidateQueries()}
      />
    );
  }

  if (gate.state === "login") {
    return <Login onLoggedIn={() => client.invalidateQueries()} />;
  }

  return (
    <div className="min-h-screen">
      <TopNav
        theme={theme}
        onToggleTheme={toggle}
        onLogout={async () => {
          await api.logout();
          await client.invalidateQueries();
        }}
      />
      <main className="mx-auto max-w-[1200px] px-4 py-6">
        <Routes>
          <Route path="/" element={<Sites />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function resolve(
  session: { isPending: boolean; error: unknown },
  setup: { data?: { token_required: boolean }; isPending: boolean },
): Gate {
  if (session.isPending) return { state: "loading" };
  if (session.error instanceof SetupRequired) {
    if (setup.isPending) return { state: "loading" };
    return { state: "setup", tokenRequired: setup.data?.token_required ?? true };
  }
  if (session.error instanceof NotAuthenticated) return { state: "login" };
  return { state: "ready" };
}
