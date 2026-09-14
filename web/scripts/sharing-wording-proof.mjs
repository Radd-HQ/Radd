#!/usr/bin/env node
/**
 * RADD-1178 proof: the view dialog's sharing panel reads as SHARING, not mail.
 *
 *   node web/scripts/sharing-wording-proof.mjs http://localhost:8000 admin@example.com change-me
 *
 * Creates a throwaway project + board, opens ⋯ → Edit view, and asserts the
 * sharing panel's visible text: "Shared with", "Unsaved changes (0)",
 * "Find people, teams or groups", "Share with someone…", the "saved with the
 * view" note — and that the word "recipient" appears nowhere in the dialog.
 * Then (RADD-1179) shares the view with a person and asserts the new share
 * appears INLINE in "Shared with" marked New, that no "Unsaved changes" tab
 * exists, that the count line reads "1 unsaved change", and that Save view
 * persists it (API read-back). Screenshots for the record; the project is
 * deleted at the end.
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: sharing-wording-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9489;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-sharing-wording-proof");
const KEY = `SW${Date.now().toString(36).slice(-4).toUpperCase()}`;
const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, { method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY };
  let projectId = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    const setup = await session.eval(`(async () => { ${API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Sharing wording" });
      const view = await api("POST", "/views", { project_id: project.body.id, name: "Wording board", view_type: "board", group_by: "state" });
      return { project: project.body, view: view.body, statuses: [project.status, view.status] };
    })()`);
    checks.setupCreated = setup.statuses.every((s) => s === 201);
    projectId = setup.project.id;

    await session.navigate(`${baseUrl}/p/${KEY}/v/${setup.view.id}`, 2500);
    const opened = await session.eval(`(() => {
      const trigger = [...document.querySelectorAll("button")].find((b) => /more|actions|menu/i.test(b.getAttribute("aria-label") || "") && !/sidebar|column/i.test(b.getAttribute("aria-label") || ""));
      if (!trigger) return [...document.querySelectorAll("button[aria-label]")].map((b) => b.getAttribute("aria-label")).slice(0, 30).join("|");
      trigger.click();
      return "opened:" + trigger.getAttribute("aria-label");
    })()`);
    context.menu = opened;
    await sleep(400);
    await session.click("[role=menuitem], button", (t) => t.trim() === "Edit view");
    await sleep(1200);
    const dialog = await session.eval(`(() => {
      const d = document.querySelector("[role=dialog]");
      if (!d) return null;
      const t = d.innerText;
      return { text: t.slice(0, 2000), hasRecipient: /recipient/i.test(t), sharedWith: /Shared with/.test(t),
        unsaved: (d.querySelector("[data-sharing-pending]")?.dataset.sharingPending === "0") && !/unsaved change/.test(t), find: /Find people, teams or groups/.test(t),
        shareWith: /Share with someone…/.test(t), note: /Sharing changes are saved with the view\\./.test(t) };
    })()`);
    context.dialog = dialog && { ...dialog, text: dialog.text.slice(-500) };
    checks.dialogOpened = Boolean(dialog);
    checks.noRecipientAnywhere = Boolean(dialog && !dialog.hasRecipient);
    checks.panelSaysSharedWith = Boolean(dialog && dialog.sharedWith);
    checks.noUnsavedCountWhenClean = Boolean(dialog && dialog.unsaved);
    checks.searchSaysFindPeopleTeamsGroups = Boolean(dialog && dialog.find);
    checks.actionSaysShareWithSomeone = Boolean(dialog && dialog.shareWith);
    checks.noteSaysSavedWithTheView = Boolean(dialog && dialog.note);
    await session.eval(`document.querySelector("[role=dialog] section[aria-label='Shared with']")?.scrollIntoView({ block: "center" })`);
    await sleep(200);
    await session.screenshot(resolve("scripts", "sharing-wording-proof.png"));
    await session.click("[role=dialog] button", (t) => t.trim() === "Share with someone…");
    await sleep(600);
    const sub = await session.eval(`(() => {
      const dialogs = [...document.querySelectorAll("[role=dialog]")];
      const top = dialogs[dialogs.length - 1];
      return top ? { title: top.querySelector("h2, h1, [id$=title]")?.textContent?.trim() ?? top.innerText.slice(0, 40), text: top.innerText } : null;
    })()`);
    context.sub = sub && { title: sub.title };
    checks.addDialogTitledShareWith = Boolean(sub && /Share with…/.test(sub.title));
    checks.addDialogHasNoRecipient = Boolean(sub && !/recipient/i.test(sub.text));

    // --- RADD-1179: add a share and watch it land inline ---
    await session.click("[role=dialog] button", (t) => t.trim() === "Choose a person, team or group…");
    await sleep(600);
    await session.eval(`(() => {
      const dialogs = [...document.querySelectorAll("[role=dialog]")];
      const top = dialogs[dialogs.length - 1];
      const input = top.querySelector("input[type=search]");
      if (!input) return "no search";
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      setter.call(input, "proof");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      return "typed";
    })()`);
    await sleep(900);
    const picked = await session.eval(`(() => {
      const dialogs = [...document.querySelectorAll("[role=dialog]")];
      const top = dialogs[dialogs.length - 1];
      const button = top.querySelector("li button");
      if (!button) return null;
      const label = button.textContent.trim();
      button.click();
      return label;
    })()`);
    context.picked = picked;
    checks.pickedSomeone = Boolean(picked);
    await sleep(400);
    await session.click("[role=dialog] button", (t) => t.trim() === "Add");
    await sleep(600);
    const inline = await session.eval(`(() => {
      const d = document.querySelector("[role=dialog]");
      const row = d?.querySelector("[data-sharing-new]");
      const tab = [...d.querySelectorAll("button")].find((b) => b.textContent.includes("Unsaved changes ("));
      const pending = d.querySelector("[data-sharing-pending]");
      return { row: row ? row.innerText.split(String.fromCharCode(10)).join(" ") : null, tab: Boolean(tab),
        pending: pending?.dataset.sharingPending ?? null, pendingText: pending?.innerText ?? "",
        firstInList: d.querySelector("section[aria-label='Shared with'] ul li")?.hasAttribute("data-sharing-new") ?? false };
    })()`);
    context.inline = inline;
    const pickedWord = (picked ?? "").split(/\s+/)[0];
    checks.newShareAppearsInline = Boolean(inline.row && /\bnew\b/i.test(inline.row) && pickedWord && inline.row.includes(pickedWord));
    checks.newShareListedFirst = inline.firstInList === true;
    checks.noUnsavedChangesTab = inline.tab === false;
    checks.countLineReadsOneUnsavedChange = inline.pending === "1" && /1 unsaved change/.test(inline.pendingText);
    await session.screenshot(resolve("scripts", "sharing-wording-proof-inline.png"));
    await session.click("[role=dialog] button", (t) => t.trim() === "Save view");
    await sleep(2000);
    const saved = await session.eval(`(async () => { ${API}
      const r = await api("GET", "/views/${setup.view.id}");
      return { status: r.status, shares: (r.body?.shares ?? []).map((s) => ({ level: s.level, name: s.user?.name ?? s.team?.name ?? s.group?.name ?? null })) };
    })()`);
    context.saved = saved;
    checks.saveViewPersistsTheShare = saved.status === 200 && saved.shares.length === 1;
  } finally {
    if (projectId) {
      await session.eval(`(async () => { ${API} return (await api("DELETE", "/projects/${projectId}")).status; })()`).catch(() => null);
    }
    await close();
  }
  report(checks, context);
}

main().catch((error) => { console.error(error); process.exit(1); });
