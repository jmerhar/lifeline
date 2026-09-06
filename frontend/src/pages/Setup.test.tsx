/** The first-run wizard. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { Setup } from "./Setup";
import { render } from "../test/render";
import { server } from "../test/server";

const GOOD = "a-good-long-password";

describe("Setup", () => {
  it("creates the administrator", async () => {
    const submitted: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/setup", async ({ request }) => {
        submitted.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: 1, username: "jure", last_login_at: null }, { status: 201 });
      }),
    );
    const onDone = vi.fn();
    render(<Setup tokenRequired onDone={onDone} />);

    await userEvent.type(screen.getByLabelText("Setup token"), "printed-token");
    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), GOOD);
    await userEvent.type(screen.getByLabelText("Password again"), GOOD);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(submitted[0]).toEqual({ username: "jure", password: GOOD, token: "printed-token" });
  });

  it("does not ask for a token when the guard is off", () => {
    render(<Setup tokenRequired={false} onDone={() => {}} />);

    expect(screen.queryByLabelText("Setup token")).not.toBeInTheDocument();
  });

  it("sends no token when none is required", async () => {
    const submitted: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/setup", async ({ request }) => {
        submitted.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: 1, username: "jure", last_login_at: null }, { status: 201 });
      }),
    );
    render(<Setup tokenRequired={false} onDone={() => {}} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), GOOD);
    await userEvent.type(screen.getByLabelText("Password again"), GOOD);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(submitted).toHaveLength(1));
    expect(submitted[0]).not.toHaveProperty("token");
  });

  it("refuses two passwords that do not match, without asking the server", async () => {
    let posted = 0;
    server.use(
      http.post("/api/setup", () => {
        posted += 1;
        return HttpResponse.json({}, { status: 201 });
      }),
    );
    render(<Setup tokenRequired={false} onDone={() => {}} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), GOOD);
    await userEvent.type(screen.getByLabelText("Password again"), "something-else");

    expect(screen.getByText("These do not match.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create account" })).toBeDisabled();
    expect(posted).toBe(0);
  });

  it("passes on a rejected token", async () => {
    server.use(
      http.post("/api/setup", () =>
        HttpResponse.json(
          { detail: "the setup token does not match the one in the container log" },
          { status: 403 },
        ),
      ),
    );
    render(<Setup tokenRequired onDone={() => {}} />);

    await userEvent.type(screen.getByLabelText("Setup token"), "wrong");
    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), GOOD);
    await userEvent.type(screen.getByLabelText("Password again"), GOOD);
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  });

  it("passes on a rejected password", async () => {
    server.use(
      http.post("/api/setup", () =>
        HttpResponse.json(
          { detail: "the password must be at least 10 characters" },
          { status: 422 },
        ),
      ),
    );
    render(<Setup tokenRequired={false} onDone={() => {}} />);

    await userEvent.type(screen.getByLabelText("Username"), "jure");
    await userEvent.type(screen.getByLabelText("Password"), "shortish");
    await userEvent.type(screen.getByLabelText("Password again"), "shortish");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("at least 10 characters");
  });
});
