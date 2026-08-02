// Publish the shared federation singletons BEFORE anything else, so plugin remotes loaded later
// resolve react / query / the SDK to the host's instances (spec 94).
import "./shared-runtime";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { createAppRouter } from "./router";
import { applyAppearance } from "./lib/theme";
import "./index.css";

// Theme/density before first paint (spec 39) — avoids a dark→light flash.
applyAppearance();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// Expose the query client for debugging + the federation live-toggle harness (invalidating the
// capabilities query is exactly what the plugins admin does to load/unload a remote live).
(globalThis as { __RADD_QUERY_CLIENT__?: QueryClient }).__RADD_QUERY_CLIENT__ = queryClient;

const router = createAppRouter(queryClient);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
