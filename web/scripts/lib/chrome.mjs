/**
 * Finding and launching the browser the proofs drive (RADD-757).
 *
 * Extracted because the launch ARGUMENTS are load-bearing and were duplicated
 * across seven scripts, which is how the blind spot below would drift back in
 * one proof at a time.
 */
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
 * Make headless Chrome admit it has a mouse.
 *
 * `--headless=new` reports `(hover: none)` and `(pointer: none)` at BASELINE —
 * before any emulation — and `Emulation.setEmulatedMedia` with `hover`/`pointer`
 * features does not change it. Tailwind v4 emits every `hover:` and
 * `group-hover:` utility inside `@media (hover: hover)`, so without this flag a
 * proof never sees hover-revealed chrome styled at all.
 *
 * That failure is indistinguishable from a product bug and points the wrong way:
 * `:hover` matches the element, the class is present, the selector matches, and
 * the computed style is still the un-hovered one. It cost most of an hour on
 * RADD-746 and nearly produced a "fix" to code that was already correct. The
 * inverse is worse — a genuinely broken hover affordance cannot be caught by a
 * proof that never renders hover styling.
 *
 * hover 2 = hover, pointer 4 = fine. Survives `Emulation.setDeviceMetricsOverride`.
 */
export const HOVER_CAPABLE =
  "--blink-settings=primaryHoverType=2,availableHoverTypes=2," +
  "primaryPointerType=4,availablePointerTypes=4";

/** The flags every proof shares. `port` and `profile` are per-proof. */
export function chromeArgs({ port, profile, extra = [] }) {
  return [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    HOVER_CAPABLE,
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    ...extra,
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
