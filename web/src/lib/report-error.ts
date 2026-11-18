/** The browser's error reports (RADD-1528).
 *
 *  Everything that catches a crash — the router's error screen, the plugin slot
 *  boundary, `window.onerror`, an unhandled rejection — hands it here, and it
 *  becomes one log line on the server.
 *
 *  Deliberately NOT the `api` client: a reporter has to work when the session
 *  is the thing that is broken, and must never redirect to /login or raise a
 *  toast of its own. It never throws and never awaits. */

import { API_BASE } from "./constants";

/** The SDK's slot boundary announces a crashed contribution with this event (it cannot import the host). */
const CLIENT_ERROR_EVENT = "radd:client-error";

export const ClientErrorSource = {
  route: "route",
  slot: "slot",
  window: "window",
  rejection: "rejection",
} as const;
export type ClientErrorSourceValue = (typeof ClientErrorSource)[keyof typeof ClientErrorSource];

/** Reports one tab sends before it goes quiet: a render loop is one bug, not a thousand lines. */
export const CLIENT_ERROR_MAX_REPORTS = 10;
const MESSAGE_MAX = 500;
const STACK_MAX = 8000;

export interface ClientErrorReport {
  message: string;
  stack: string;
  route: string;
  source: string;
  plugin: string;
  build: string;
}

/** Shape whatever was thrown into the wire report. Pure: the route and build are passed in. */
export function describeClientError(
  error: unknown,
  source: string,
  context: { route: string; build: string; plugin?: string },
): ClientErrorReport {
  const known = error instanceof Error;
  const message = known ? `${error.name}: ${error.message}` : String(error ?? "unknown error");
  return {
    message: (message || "unknown error").slice(0, MESSAGE_MAX),
    stack: (known ? (error.stack ?? "") : "").slice(0, STACK_MAX),
    // Path only: a query string can carry search text or a token.
    route: context.route.split(/[?#]/)[0].slice(0, 300),
    source,
    plugin: (context.plugin ?? "").slice(0, 100),
    build: context.build.slice(0, 40),
  };
}

/** Whether to send `report`, given what this tab already sent. Identical errors go once. */
export function admitClientError(sent: Set<string>, report: ClientErrorReport): boolean {
  if (sent.size >= CLIENT_ERROR_MAX_REPORTS) return false;
  const identity = `${report.source}|${report.plugin}|${report.message}`;
  if (sent.has(identity)) return false;
  sent.add(identity);
  return true;
}

const sent = new Set<string>();

/** The hashed entry chunk names the build a tab is running — a stale tab reports ITS build. */
function buildId(): string {
  const entry = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]');
  return entry?.src.split("/").pop()?.replace(/\.js$/, "") ?? "";
}

export function reportClientError(error: unknown, source: ClientErrorSourceValue, plugin?: string): void {
  try {
    const report = describeClientError(error, source, {
      route: window.location.pathname,
      build: buildId(),
      plugin,
    });
    if (!admitClientError(sent, report)) return;
    void fetch(`${API_BASE}/client-errors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
      credentials: "same-origin",
      keepalive: true, // survives the reload an error screen offers
    }).catch(() => undefined);
  } catch {
    // A reporter that throws would report itself, forever.
  }
}

export function installClientErrorReporting(): void {
  window.addEventListener("error", (event) => {
    // A failed <img>/<script> load also fires `error`, with no error object: not a crash.
    if (event.error) reportClientError(event.error, ClientErrorSource.window);
  });
  window.addEventListener("unhandledrejection", (event) => {
    reportClientError(event.reason, ClientErrorSource.rejection);
  });
  window.addEventListener(CLIENT_ERROR_EVENT, (event) => {
    const detail = (event as CustomEvent<{ error: unknown; plugin?: string }>).detail;
    reportClientError(detail?.error, ClientErrorSource.slot, detail?.plugin);
  });
}
