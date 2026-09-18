#!/usr/bin/env node
/**
 * RADD-1227 proof (GitHub #5): a freshly created API token is HIDDEN by
 * default, Copy is the action, Reveal is opt-in.
 *
 *   node web/scripts/secret-mask-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in, creates a throwaway personal token through the real form, and
 * measures in the browser that:
 *   1. the panel shows the token's prefix + a mask, and the full secret is
 *      nowhere in the page text;
 *   2. Copy puts the FULL token on the clipboard while the panel stays masked;
 *   3. Reveal (aria-pressed) shows the secret, Hide takes it away again;
 *   4. the mask carries no length information (fixed width);
 *   5. with the clipboard DENIED, Copy reports the failure and does NOT reveal.
 * The token is revoked at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: secret-mask-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9489;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-secret-mask-proof");
const NAME = `mask-proof-${Date.now().toString(36).slice(-5)}`;

const STATE = `(() => {
  const wrap = document.querySelector("[data-copy-value]");
  const code = wrap?.querySelector('[data-testid="copy-value"]');
  const reveal = wrap ? [...wrap.querySelectorAll("button")].find((b) => /Reveal|Hide/.test(b.textContent)) : null;
  const copy = wrap ? [...wrap.querySelectorAll("button")].find((b) => /^Cop/.test(b.textContent.trim())) : null;
  const status = wrap?.querySelector('[role="status"]')?.textContent?.trim() ?? null;
  return {
    mode: wrap?.getAttribute("data-copy-value") ?? null,
    text: code?.textContent ?? null,
    codeWidth: code ? Math.round(code.getBoundingClientRect().width) : null,
    revealLabel: reveal?.textContent?.trim() ?? null,
    revealPressed: reveal?.getAttribute("aria-pressed") ?? null,
    copyLabel: copy?.textContent?.trim() ?? null,
    status,
    bodyHasPat: /radd_pat_[A-Za-z0-9_-]{20,}/.test(document.body.innerText),
  };
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 900 });
  const checks = {};
  const context = { name: NAME };
  let tokenId = null;
  const state = () => session.eval(STATE);
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);
    await session.navigate(baseUrl + "/settings/tokens", 2500);

    // Create through the real form: type the name, submit.
    await session.eval(`(() => {
      const input = [...document.querySelectorAll("input")].find((i) => i.placeholder === "ci-importer");
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(input, ${JSON.stringify(NAME)});
      input.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(200);
    await session.click("button[type=submit]", (t) => /Create token/.test(t));
    await sleep(2000);

    // The list row knows the id (for cleanup) and the prefix (for the hint check).
    const row = await session.eval(`(async () => {
      const r = await fetch("/api/v1/tokens"); const rows = await r.json();
      const mine = rows.find((t) => t.name === ${JSON.stringify(NAME)});
      return mine ? { id: mine.id, prefix: mine.prefix_display } : null;
    })()`);
    context.row = row;
    tokenId = row?.id ?? null;

    // 1. hidden by default
    let s = await state();
    context.initial = s;
    checks.panelRendered = s.mode === "hidden";
    checks.secretNotInPageText = s.bodyHasPat === false;
    checks.maskShowsPrefix = Boolean(row?.prefix) && s.text?.startsWith(row.prefix) === true && /•{8,}/.test(s.text ?? "");
    checks.revealIsOptIn = s.revealLabel === "Reveal" && s.revealPressed === "false";
    await session.screenshot(resolve("scripts", "secret-mask-proof-hidden.png"));

    // 2. copy the full token while hidden
    await session.send("Browser.grantPermissions", {
      origin: new URL(baseUrl).origin,
      permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"],
    });
    await session.click("[data-copy-value] button", (t) => /^Cop/.test(t.trim()));
    await sleep(300);
    const clipboard = await session.eval(`navigator.clipboard.readText()`).catch(() => null);
    s = await state();
    context.afterCopy = { ...s, clipboardPrefixOk: clipboard?.startsWith(row?.prefix ?? "?") };
    checks.copyPutsFullTokenOnClipboard =
      typeof clipboard === "string" && /^radd_pat_[A-Za-z0-9_-]{20,}$/.test(clipboard) && clipboard.startsWith(row?.prefix ?? "?");
    checks.copyKeepsItHidden = s.mode === "hidden" && s.copyLabel === "Copied" && s.bodyHasPat === false;

    // 3. reveal, then hide
    await session.click("[data-copy-value] button", (t) => /Reveal/.test(t));
    await sleep(200);
    s = await state();
    context.revealed = s;
    checks.revealShowsSecret = s.mode === "revealed" && s.revealPressed === "true" && s.text === clipboard;
    await session.screenshot(resolve("scripts", "secret-mask-proof-revealed.png"));
    await session.click("[data-copy-value] button", (t) => /Hide/.test(t));
    await sleep(200);
    s = await state();
    context.hiddenAgain = s;
    checks.hideTakesItAway = s.mode === "hidden" && s.bodyHasPat === false;

    // 4. the mask is a fixed width, unrelated to the secret's length
    const maskChars = (s.text ?? "").replace(row?.prefix ?? "", "").replace(/[^•]/g, "").length;
    context.maskChars = { maskChars, secretLength: clipboard?.length ?? null };
    checks.maskLeaksNoLength = maskChars === 24 && maskChars !== (clipboard?.length ?? -1);

    // 5. clipboard denied: copy fails loudly and does not reveal
    await session.send("Browser.resetPermissions");
    await session.send("Browser.setPermission", {
      origin: new URL(baseUrl).origin,
      permission: { name: "clipboard-write" },
      setting: "denied",
    }).catch(() => null);
    await session.eval(`(() => { Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) }, configurable: true }); })()`);
    await session.click("[data-copy-value] button", (t) => /^Cop/.test(t.trim()));
    await sleep(300);
    s = await state();
    context.denied = s;
    checks.deniedCopyReportsAndStaysHidden =
      s.mode === "hidden" && /Couldn't copy/.test(s.status ?? "") && /Reveal/.test(s.status ?? "") && s.bodyHasPat === false;
  } finally {
    if (tokenId) {
      await session.eval(`(async () => (await fetch("/api/v1/tokens/${tokenId}", { method: "DELETE" })).status)()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
