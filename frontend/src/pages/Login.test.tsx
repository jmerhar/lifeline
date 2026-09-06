/** The login screen. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { Login } from "./Login";
import { render } from "../test/render";
import { server } from "../test/server";

describe("Login", () => {
  it("signs in", async () => {
    const onLoggedIn = vi.fn();
    render(<Login onLoggedIn={onLoggedIn} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), "a-good-long-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(onLoggedIn).toHaveBeenCalled());
  });

  it("passes on what the server said about a wrong password", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({ detail: "incorrect username or password" }, { status: 401 }),
      ),
    );
    render(<Login onLoggedIn={() => {}} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("did not work");
  });

  it("says to wait when the attempts are being throttled", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { detail: "too many login attempts; wait a minute and try again" },
          { status: 429 },
        ),
      ),
    );
    render(<Login onLoggedIn={() => {}} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("too many login attempts");
  });
});
