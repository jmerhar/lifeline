/** Rendering a component with the providers the app gives it. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as rtlRender, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { routerFuture } from "../router";

export function render(ui: ReactElement, { route = "/" } = {}): RenderResult {
  // Retries off and no caching between tests: a test asserting on an error state should not
  // wait through a retry, and one test's data must never satisfy the next test's query.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return rtlRender(
    <QueryClientProvider client={client}>
      <MemoryRouter future={routerFuture} initialEntries={[route]}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
