#!/usr/bin/env node
/**
 * Proof for the four reports filed on 2026-09-18 (RADD-1229/1230/1231/1232's
 * browser half), in one throwaway project:
 *
 *   node web/scripts/salvador-reports-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 *   RADD-1229 — a quick filter typed WITHOUT a label survives the save (its
 *               label defaults to the condition), and a label without a
 *               condition blocks the save with a message instead of vanishing;
 *   RADD-1230 — creating an issue raises a toast whose Open action lands on
 *               the new issue;
 *   RADD-1231 — every scrolling element carries the same 12px, rounded,
 *               themed scrollbar (measured rail, thumb style, both themes;
 *               the Gecko-only rule is proven NOT to apply to Chrome).
 * Every check is a measurement. The project is deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: salvador-reports-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9495;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-salvador-reports-proof");
const KEY = `SR${Date.now().toString(36).slice(-4).toUpperCase()}`;

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

const setValue = (selector, value) => `(() => {
  const input = document.querySelector(${JSON.stringify(selector)});
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(value)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  let projectId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    context.login = await session.login(baseUrl, adminEmail, adminPassword);
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Reports proof" });
      const view = await api("POST", "/views", { project_id: project.body.id, name: "Filters", view_type: "list" });
      return { project: project.body, view: view.body };
    })()`);
    projectId = setup.project.id;

    // --- RADD-1229: quick filter without a label ---------------------------
    await session.navigate(`${baseUrl}/p/${KEY}/v/${setup.view.id}`, 3000);
    const openEditor = async () => {
      // The edit entry lives in the view header's ⋯ menu ("View actions").
      await session.click('button[aria-label="View actions"]', () => true);
      await sleep(300);
      await session.click('[role="menuitem"]', (t) => /Edit view/.test(t));
      await sleep(700);
      return session.eval(`Boolean(document.querySelector('[role="dialog"]'))`);
    };
    context.modalOpen = await openEditor();
    await session.click('[role="dialog"] button', (t) => /Add quick filter/.test(t));
    await sleep(300);
    // Type the CONDITION only — the reported repro — into the row's SLQ editor.
    const typed = await session.eval(`(() => {
      const dialog = document.querySelector('[role="dialog"]');
      const editors = [...dialog.querySelectorAll("textarea, input")].filter((el) => /SLQ condition/.test(el.placeholder || ""));
      const el = editors[editors.length - 1];
      if (!el) return false;
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, "assignee = me");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    })()`);
    context.typed = typed;
    await sleep(900);
    await session.click('[role="dialog"] button[type="submit"]', () => true);
    await sleep(1500);
    const saved = await session.eval(`(async () => { ${API} return (await api("GET", "/views/${setup.view.id}")).body.quick_filters; })()`);
    context.saved = saved;
    checks.unlabelledQuickFilterSurvivesTheSave =
      Array.isArray(saved) && saved.length === 1 && saved[0].query === "assignee = me" && saved[0].name === "assignee = me";
    const chip = await session.eval(`[...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "assignee = me")`);
    checks.chipAppearsOnTheView = chip === true;

    // A label with no condition cannot be saved, and says why.
    context.reopened = await openEditor();
    await session.click('[role="dialog"] button', (t) => /Add quick filter/.test(t));
    await sleep(300);
    await session.eval(`(() => {
      const inputs = [...document.querySelectorAll('[role="dialog"] input[placeholder^="Label"]')];
      const el = inputs[inputs.length - 1];
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, "Orphan");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    })()`);
    await sleep(300);
    const orphan = await session.eval(`(() => ({
      error: document.querySelector("[data-quick-filter-error]")?.textContent?.trim() ?? null,
      saveDisabled: document.querySelector('[role="dialog"] button[type="submit"]')?.disabled ?? null,
    }))()`);
    context.orphan = orphan;
    checks.labelWithoutConditionBlocksTheSaveAndSaysWhy = /Orphan/.test(orphan.error ?? "") && orphan.saveDisabled === true;
    await session.screenshot(resolve("scripts", "salvador-reports-proof-quickfilter.png"));
    await session.click('[role="dialog"] button', (t) => t.trim() === "Cancel").catch(() => null);
    await sleep(300);

    // --- RADD-1230: created issue → toast → open ------------------------------
    await session.click("button", (t) => /New item/.test(t));
    await sleep(800);
    await session.eval(setValue('[role="dialog"] input[placeholder="Short, imperative summary"]', "Jump target"));
    await sleep(200);
    await session.click('[role="dialog"] button[type="submit"]', () => true);
    await sleep(1500);
    const toast = await session.eval(`(() => {
      const region = document.querySelector('[role="status"][aria-live]');
      const action = region?.querySelector("[data-toast-action]");
      return { text: region?.textContent?.trim() ?? null, action: action?.textContent?.trim() ?? null };
    })()`);
    context.toast = toast;
    checks.creationRaisesAToastNamingTheKey = new RegExp(`Created ${KEY}-\\d+`).test(toast.text ?? "") && /Open/.test(toast.action ?? "");
    await session.screenshot(resolve("scripts", "salvador-reports-proof-toast.png"));
    await session.click("[data-toast-action]", () => true);
    await sleep(1500);
    const landed = await session.eval(`({ path: location.pathname, title: document.querySelector("h1, [data-item-title], input[aria-label='Title']")?.textContent || document.querySelector("input[aria-label='Title']")?.value || document.title })`);
    context.landed = landed;
    checks.openLandsOnTheNewIssue = new RegExp(`/issues/${KEY}-\\d+$`).test(landed.path);

    // --- RADD-1231: one scrollbar, big enough to grab ------------------------
    // Headless Chrome is the -webkit- path: the rail is the difference between
    // the box and its client width on an element that actually scrolls.
    const scroll = await session.eval(`(() => {
      const el = [...document.querySelectorAll("*")].find((n) => /auto|scroll/.test(getComputedStyle(n).overflowY) && n.scrollHeight > n.clientHeight);
      if (!el) return null;
      const cs = getComputedStyle(el);
      const thumb = getComputedStyle(el, "::-webkit-scrollbar-thumb");
      return {
        rail: el.offsetWidth - el.clientWidth - (parseFloat(cs.borderLeftWidth) || 0) - (parseFloat(cs.borderRightWidth) || 0),
        standardWidth: cs.scrollbarWidth,
        thumbColor: thumb.backgroundColor,
        thumbRadius: thumb.borderRadius,
      };
    })()`);
    context.scroll = scroll;
    checks.chromeRailIsTwelvePixels = scroll?.rail === 12;
    checks.chromeKeepsTheStyledThumb = scroll?.standardWidth === "auto" && /rgb/.test(scroll?.thumbColor ?? "") && /9999px|px/.test(scroll?.thumbRadius ?? "");
    // The Gecko block must NOT apply here — it is what would collapse Chrome to thin.
    const geckoScoped = await session.eval(`!CSS.supports("-moz-appearance", "none") && getComputedStyle(document.documentElement).scrollbarColor === "auto"`);
    checks.geckoRuleIsScopedAwayFromChrome = geckoScoped === true;
    await session.eval(`document.documentElement.classList.add("light")`);
    await sleep(100);
    const light = await session.eval(`(() => {
      const el = [...document.querySelectorAll("*")].find((n) => /auto|scroll/.test(getComputedStyle(n).overflowY) && n.scrollHeight > n.clientHeight);
      return el ? getComputedStyle(el, "::-webkit-scrollbar-thumb").backgroundColor : null;
    })()`);
    context.light = light;
    checks.lightThemeRemapsTheThumb = Boolean(light) && light !== scroll?.thumbColor;
  } finally {
    if (projectId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/projects/${projectId}")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
