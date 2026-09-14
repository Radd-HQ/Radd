#!/usr/bin/env node
/**
 * RADD-1174 proof: a project can be deleted from Settings → Project → General,
 * and the dialog tells the truth before it happens.
 *
 *   node web/scripts/project-delete-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Signs in as an instance admin, creates a throwaway project with one issue and
 * one comment over the API, then checks in a REAL browser that:
 *   1. the Danger zone renders on General and opens the dialog;
 *   2. with a mail source defaulting to the project, the dialog shows the
 *      blocker, links to Settings → Email, and the danger button stays disabled
 *      even with the key typed;
 *   3. with the source repointed, the dialog reports the server's counts
 *      (1 issue, 1 comment), the button is disabled until the KEY is typed, and
 *      clicking it deletes the project — the browser lands on /projects and the
 *      API answers 404.
 * Every check is a measurement (DOM state, API read-back).
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: project-delete-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9483;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-project-delete-proof");
const KEY = `PX${Date.now().toString(36).slice(-4).toUpperCase()}`;

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

const DIALOG = `(() => {
  const dialog = document.querySelector("[role=dialog]");
  if (!dialog) return null;
  const buttons = [...dialog.querySelectorAll("button")];
  const danger = buttons.find((b) => /Delete permanently|Deleting/.test(b.textContent));
  const input = dialog.querySelector("input");
  return {
    text: dialog.innerText,
    dangerDisabled: danger ? danger.disabled : null,
    inputDisabled: input ? input.disabled : null,
    emailLink: dialog.querySelector('a[href$="/settings/email"]') !== null,
  };
})()`;

async function typeKey(session, value) {
  await session.eval(`(() => {
    const input = document.querySelector("[role=dialog] input");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  await sleep(200);
}

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  let sourceId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);

    // --- setup over the API: a project with one issue + one comment, and a
    // mail source that lands in it (the blocker) ---
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Delete proof" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "the only issue" });
      const comment = await api("POST", "/items/" + item.body.id + "/comments", { body: "the only comment" });
      const source = await api("POST", "/mail/sources", { name: "Proof source " + ${JSON.stringify(KEY)}, kind: "webhook",
        address: ${JSON.stringify(KEY.toLowerCase())} + "@example.test", default_project_id: project.body.id, secret: "proof" });
      return { project: project.body, source: source.body, statuses: [project.status, item.status, comment.status, source.status] };
    })()`);
    context.setup = setup.statuses;
    checks.setupCreated = setup.statuses.every((s) => s === 201);
    const { project, source } = setup;
    sourceId = source && source.id;

    // --- 1. the Danger zone on General ---
    await session.navigate(`${baseUrl}/p/${KEY}/settings/general`, 2500);
    const zone = await session.eval(`(() => {
      const card = document.querySelector("[data-project-danger]");
      return card ? { text: card.innerText, hasButton: [...card.querySelectorAll("button")].some((b) => b.textContent.includes("Delete project")) } : null;
    })()`);
    context.zone = zone && zone.text.slice(0, 80);
    checks.dangerZoneRendered = Boolean(zone && zone.hasButton && zone.text.includes(KEY));
    await session.screenshot(resolve("scripts", "project-delete-proof-zone.png"));

    // --- 2. blocked: the dialog names the source and the button stays off ---
    await session.click("[data-project-danger] button", (t) => t.includes("Delete project"));
    await sleep(1200);
    let dialog = await session.eval(DIALOG);
    context.blocked = dialog && dialog.text.slice(0, 200);
    checks.dialogOpened = Boolean(dialog);
    checks.blockerNamed = Boolean(dialog && dialog.text.includes("Proof source " + KEY) && dialog.text.includes("routes mail"));
    checks.blockerLinksToEmailSettings = Boolean(dialog && dialog.emailLink);
    checks.blockedInputDisabled = Boolean(dialog && dialog.inputDisabled === true);
    checks.blockedButtonDisabled = Boolean(dialog && dialog.dangerDisabled === true);
    await session.screenshot(resolve("scripts", "project-delete-proof-blocked.png"));
    // the server refuses too, whatever the browser shows
    const refused = await session.eval(`(async () => { ${API} return (await api("DELETE", "/projects/${project.id}")).status; })()`);
    context.refusedStatus = refused;
    checks.serverRefusesWhileBlocked = refused === 409;

    // remove the source (the admin's fix), close + reopen the dialog
    const removed = await session.eval(`(async () => { ${API}
      return (await api("DELETE", "/mail/sources/${source.id}")).status;
    })()`);
    checks.sourceRemoved = removed === 204;
    if (removed === 204) sourceId = null;
    await session.click("[role=dialog] button", (t) => t.trim() === "Cancel");
    await sleep(400);
    await session.click("[data-project-danger] button", (t) => t.includes("Delete project"));
    await sleep(1200);

    // --- 3. the honest dialog, then the deletion ---
    dialog = await session.eval(DIALOG);
    context.counts = dialog && dialog.text.slice(0, 240);
    checks.countsShown = Boolean(dialog && /1 issues/.test(dialog.text) && /1 comments/.test(dialog.text));
    checks.noBlockerNow = Boolean(dialog && !dialog.text.includes("routes mail"));
    checks.buttonOffUntilKeyTyped = Boolean(dialog && dialog.dangerDisabled === true && dialog.inputDisabled === false);
    await typeKey(session, "WRONG");
    checks.wrongKeyKeepsButtonOff = (await session.eval(DIALOG)).dangerDisabled === true;
    await typeKey(session, KEY.toLowerCase());
    checks.keyTypedEnablesButton = (await session.eval(DIALOG)).dangerDisabled === false;
    await session.screenshot(resolve("scripts", "project-delete-proof-armed.png"));
    await session.click("[role=dialog] button", (t) => t.trim() === "Delete permanently");
    await sleep(2500);
    const after = await session.eval(`(async () => { ${API}
      const r = await api("GET", "/projects/${project.id}");
      return { path: location.pathname, status: r.status, toast: document.body.innerText.includes("deleted") };
    })()`);
    context.after = after;
    checks.landedOnProjectsIndex = after.path === "/projects";
    checks.projectGoneFromApi = after.status === 404;
    checks.toastConfirmed = after.toast === true;
  } finally {
    // the throwaway mail source must not outlive the proof
    if (sourceId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/mail/sources/${sourceId}")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
