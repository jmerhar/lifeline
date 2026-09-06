/** Test environment setup, loaded before every suite. */

import "@testing-library/jest-dom/vitest";

import { afterAll, afterEach, beforeAll, beforeEach } from "vitest";

import { installLocalStorage } from "./localStorage";
import { server } from "./server";

// Unhandled requests fail rather than fall through to the network: a test that quietly
// reaches a real host is a test whose result depends on somebody else's uptime.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Cleared between tests so one test's remembered theme cannot decide another's starting state.
beforeEach(() => installLocalStorage().clear());
