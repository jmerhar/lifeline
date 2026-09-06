/** Which of the three states the app shows, and that navigation works once it is in use. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { loggedOut, setupRequired } from "./test/handlers";
import { render } from "./test/render";
import { server } from "./test/server";

describe("App", () => {
  it("shows the wizard when the instance has no administrator", async () => {
    server.use(...setupRequired);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Set up lifeline" })).toBeInTheDocument();
  });

  it("asks for the setup token, and says where to find it", async () => {
    // Whoever finds the URL first must not be able to claim the instance.
    server.use(...setupRequired);

    render(<App />);

    expect(await screen.findByLabelText(/Setup token/)).toBeInTheDocument();
    expect(screen.getByText(/docker compose logs lifeline/)).toBeInTheDocument();
  });

  it("shows the login form when nobody is logged in", async () => {
    server.use(...loggedOut);

    render(<App />);

    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the sites once someone is logged in", async () => {
    render(<App />);

    expect(await screen.findByRole("link", { name: "Sites" })).toBeInTheDocument();
    expect(await screen.findByText("example")).toBeInTheDocument();
  });

  it("moves between the screens", async () => {
    render(<App />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("link", { name: "Settings" }));

    expect(await screen.findByRole("heading", { name: "Notifications" })).toBeInTheDocument();
  });

  it("switches the theme and remembers the choice", async () => {
    render(<App />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: /light theme/ }));

    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    expect(window.localStorage.getItem("lifeline-theme")).toBe("light");
  });

  it("logs out", async () => {
    let loggedOutCalls = 0;
    server.use(
      http.post("/api/auth/logout", () => {
        loggedOutCalls += 1;
        return HttpResponse.json({ detail: "logged out" });
      }),
    );
    render(<App />);
    await screen.findByText("example");

    await userEvent.click(screen.getByRole("button", { name: "Log out" }));

    await waitFor(() => expect(loggedOutCalls).toBe(1));
  });

  it("sends an unknown path back to the sites", async () => {
    render(<App />, { route: "/nonsense" });

    expect(await screen.findByText("example")).toBeInTheDocument();
  });
});
