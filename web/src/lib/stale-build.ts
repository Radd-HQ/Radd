/** A tab that outlives a deploy (RADD-1527).
 *
 *  Every route and plugin page is a lazy chunk with a content hash in its name,
 *  and a release replaces the whole bundle. A tab opened before the release
 *  still runs the old entry chunk; its next navigation imports a hash that no
 *  longer exists. Vite reports that as `vite:preloadError`. The remedy is the
 *  one the user would find by trial: reload, which fetches the current
 *  `index.html` (served `no-cache`) and with it the current hashes. It applies
 *  only when the server really has another build: the shell is fetched and
 *  compared first, so a chunk that failed for any other reason is left to the
 *  handling it already has.
 *
 *  Reload ONCE. A chunk that is missing from the CURRENT build would otherwise
 *  reload forever, so a second failure inside the window is left to surface as
 *  an ordinary error. */

const STORAGE_KEY = "radd:stale-build-reload";
/** Two failures closer together than this are the same broken build, not two deploys. */
export const STALE_BUILD_RELOAD_WINDOW_MS = 60_000;

/** Whether a chunk failure at `now` should reload, given when the last reload happened. */
export function shouldReloadForStaleBuild(lastReloadAt: number | null, now: number): boolean {
  return lastReloadAt === null || now - lastReloadAt > STALE_BUILD_RELOAD_WINDOW_MS;
}

function lastReload(): number | null {
  try {
    const stored = Number(window.sessionStorage.getItem(STORAGE_KEY));
    return Number.isFinite(stored) && stored > 0 ? stored : null;
  } catch {
    return null; // storage blocked: treated as "never", bounded by the browser's own reload
  }
}

/** The hashed entry chunk this tab booted from: its name IS the build. */
function runningEntry(): string | null {
  const entry = document.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]');
  return entry ? new URL(entry.src).pathname : null;
}

/** Whether the server's current shell still references the entry this tab runs.
 *  Pure, so the decision is testable: `shell` is the fetched index.html. */
export function buildIsStale(runningEntryPath: string | null, shell: string): boolean {
  return runningEntryPath !== null && !shell.includes(runningEntryPath);
}

export function reloadOnStaleBuild(): void {
  window.addEventListener("vite:preloadError", () => {
    const now = Date.now();
    if (!shouldReloadForStaleBuild(lastReload(), now)) return; // let the error reach the screen
    // Reload ONLY when the server has moved on to another build (see the header):
    // any other chunk failure keeps the handling it already has.
    void fetch("/", { cache: "no-store", credentials: "same-origin" })
      .then((response) => (response.ok ? response.text() : ""))
      .then((shell) => {
        if (!shell || !buildIsStale(runningEntry(), shell)) return;
        try {
          window.sessionStorage.setItem(STORAGE_KEY, String(now));
        } catch {
          return; // cannot remember the attempt, so cannot promise it happens once
        }
        window.location.reload();
      })
      .catch(() => undefined); // offline: nothing a reload would fix
  });
}
