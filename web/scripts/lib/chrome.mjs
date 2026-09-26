/** Finding and launching the browser the proofs drive (RADD-757): the launch ARGUMENTS are
 *  load-bearing, so they live in one place. */
import { existsSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";

/** Chrome from `$RADD_CHROME`, then Playwright's cache, then the system. */
export function findChrome() {
  if (process.env.RADD_CHROME && existsSync(process.env.RADD_CHROME)) return process.env.RADD_CHROME;
  const base = resolve(homedir(), ".cache/ms-playwright");
  if (existsSync(base)) {
    for (const dir of readdirSync(base)) {
      for (const leaf of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
        const p = resolve(base, dir, leaf);
        if (existsSync(p)) return p;
      }
    }
  }
  for (const p of ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]) {
    if (existsSync(p)) return p;
  }
  throw new Error("no Chrome/Chromium found (set $RADD_CHROME)");
}

/**
 * Make headless Chrome admit it has a mouse. `--headless=new` reports `(hover: none)` and
 * `(pointer: none)` at baseline (setEmulatedMedia cannot change it) and Tailwind v4 wraps every
 * `hover:`/`group-hover:` in `@media (hover: hover)`, so without this flag hover-revealed chrome
 * is never styled — which reads exactly like a product bug (RADD-746).
 * hover 2 = hover, pointer 4 = fine; survives setDeviceMetricsOverride.
 */
export const HOVER_CAPABLE =
  "--blink-settings=primaryHoverType=2,availableHoverTypes=2," +
  "primaryPointerType=4,availablePointerTypes=4";

/** The flags every proof shares. `port` and `profile` are per-proof. */
export function chromeArgs({ port, profile }) {
  return [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    HOVER_CAPABLE,
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "about:blank",
  ];
}

/**
 * Ask the page whether the flag took.
 *
 * Every proof should assert this. A launch flag that silently stops working
 * would return the whole suite to blindness without a single failure.
 */
export const HOVER_CAPABLE_PROBE = `matchMedia("(hover: hover)").matches`;
