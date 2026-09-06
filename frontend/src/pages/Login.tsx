/** The login screen. */

import { useState } from "react";

import { api, ApiError } from "../api/client";
import { Wordmark } from "../components/Mark";
import { Button, Card, Field, Input, Problem } from "../components/ui";

export function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login({ username, password });
      onLoggedIn();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "That username and password did not work.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-6 px-4 py-12">
      <Wordmark />
      <Card className="p-4">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Username">
            <Input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </Field>
          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>
          {error ? <Problem>{error}</Problem> : null}
          <Button tone="primary" type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
