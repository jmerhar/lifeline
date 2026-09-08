/** The entry point: fonts, query client, router, app. */

import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./App";
import { routerFuture } from "./router";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // Nothing here changes on its own faster than a person can press a button, and every
      // mutation invalidates what it touched.
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <BrowserRouter future={routerFuture}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
