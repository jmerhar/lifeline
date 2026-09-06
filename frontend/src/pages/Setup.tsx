/**
 * The first screen a new instance shows.
 *
 * The token is asked for because this instance may be reachable from the internet before
 * anyone has configured it, and without it whoever found the URL first would own it. Where
 * to find the token is printed on the screen rather than left to be looked up.
 */

import { useState } from "react";

import { api, ApiError } from "../api/client";
import { Wordmark } from "../components/Mark";
import { Button, Card, Field, Input, Problem } from "../components/ui";

export function Setup({
  tokenRequired,
  onDone,
}: {
  tokenRequired: boolean;
  onDone: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = confirmation.length > 0 && password !== confirmation;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirmation) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.completeSetup({
        username,
        password,
        ...(tokenRequired ? { token } : {}),
      });
      onDone();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Setup could not be completed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-4 py-12">
      <div className="flex flex-col gap-2">
        <Wordmark />
        <h1 className="text-display font-medium tracking-[-0.01em]">Set up lifeline</h1>
        <p className="text-small text-muted">
          Create the account you will use to manage the sites this instance keeps alive.
        </p>
      </div>

      <Card className="p-4">
        <form onSubmit={submit} className="flex flex-col gap-4">
          {tokenRequired ? (
            <Field
              label="Setup token"
              hint="Printed in this container's log at startup: docker compose logs lifeline"
            >
              <Input
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                required
              />
            </Field>
          ) : null}

          <Field label="Username">
            <Input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </Field>

          <Field label="Password" hint="At least 10 characters.">
            <Input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              minLength={10}
              required
            />
          </Field>

          <Field label="Password again" error={mismatch ? "These do not match." : undefined}>
            <Input
              type="password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              autoComplete="new-password"
              required
            />
          </Field>

          {error ? <Problem>{error}</Problem> : null}

          <Button tone="primary" type="submit" disabled={busy || mismatch}>
            {busy ? "Creating the account…" : "Create account"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
