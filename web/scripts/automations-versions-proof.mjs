/**
 * Versioned automations (RADD-1268, delivering RADD-1111).
 *
 * Proves, against a running server:
 *   - three saves make three versions, and toggling enabled makes none;
 *   - restoring v1 makes v4 with v1's content, leaving v2 and v3 in place;
 *   - the editor's Versions tab lists them with the current one marked, a
 *     selected version previews read-only on its own canvas, and Restore goes
 *     through the confirm dialog and reloads the editor onto the restored graph.
 *
 * Usage: node scripts/automations-versions-proof.mjs [--base http://localhost:8000]
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9359, profile: "/tmp/radd-versions" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`}});` +
  `return {status:r.status, body: await r.text()};})()`;
const parsed = (r) => (r.status < 300 ? JSON.parse(r.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

const suffix = Math.random().toString(36).slice(2, 6);
const graph = (label, extra = []) => ({
  nodes: [
    { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
    { id: "act1", kind: "action", type: "action.add_label", params: { label } },
    ...extra,
  ],
  edges: [{ source: "trg1", port: "out", target: "act1" }, ...extra.map((n) => ({ source: "act1", port: "out", target: n.id }))],
});

// --- three versions by API ----------------------------------------------------
const rule = parsed(await session.eval(api("POST", "/automations", {
  name: `versions proof ${suffix}`, enabled: false, orientation: "vertical", note: "v1: the start", ...graph("one"),
})));
const v2 = parsed(await session.eval(api("PATCH", `/automations/${rule?.id}`, { ...graph("two"), note: "v2: relabel" })));
const v3 = parsed(await session.eval(api("PATCH", `/automations/${rule?.id}`, {
  ...graph("three", [{ id: "act2", kind: "action", type: "action.add_comment", params: { body: "third", visibility: "public" } }]),
  note: "v3: a comment too",
})));
const toggled = parsed(await session.eval(api("PATCH", `/automations/${rule?.id}`, { enabled: true })));
const listed = parsed(await session.eval(api("GET", `/automations/${rule?.id}/versions`))) ?? [];
const restored = parsed(await session.eval(api("POST", `/automations/${rule?.id}/versions/1/restore`, { note: "back to v1" })));
const afterRestore = parsed(await session.eval(api("GET", `/automations/${rule?.id}/versions`))) ?? [];
const v4 = parsed(await session.eval(api("GET", `/automations/${rule?.id}/versions/4`)));

// --- the editor --------------------------------------------------------------
await session.navigate(`${baseUrl}/settings/automations`, 2500);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes(${JSON.stringify(`versions proof ${suffix}`)}));if(el)el.click();return !!el;})()`,
);
await sleep(2500);
const openedTab = await session.eval(
  `(()=>{const tab=[...document.querySelectorAll('[role="tab"]')].find(t=>/^Versions$/.test(t.textContent.trim()));
     if(!tab) return false; tab.click(); return true;})()`,
);
await sleep(1500);
const rows = await session.eval(
  `[...document.querySelectorAll("[data-versions-list] [data-version-row]")].map(r=>({v:r.getAttribute("data-version-row"),current:!!r.querySelector("[data-version-current]"),text:r.innerText.replace(/\\s+/g," ").trim()}))`,
);
// Preview v3 (the one with two actions).
await session.eval(`(()=>{const b=document.querySelector('[data-version-row="3"] button[aria-expanded]'); if(b) b.click(); return !!b;})()`);
await sleep(2500);
const previewNodes = await session.eval(
  `document.querySelectorAll('[data-version-preview="3"] [data-node-id]').length`,
);
// Restore v3 through the dialog: the editor should reload onto three nodes.
await session.eval(`(()=>{const b=document.querySelector('[data-version-row="3"] button[aria-label="Restore version 3"]'); if(b) b.click(); return !!b;})()`);
await sleep(700);
const dialogShown = await session.eval(`/Restore version 3\\?/.test(document.body.innerText)`);
// The dialog is portaled after the rows, whose own Restore buttons match the
// same text — so the search is scoped to the dialog, and reports whether it
// found one at all.
const confirmed = await session.eval(`(()=>{const dialog=document.querySelector('[role="dialog"], [role="alertdialog"], dialog');
  const b=dialog&&[...dialog.querySelectorAll("button")].find(x=>/^Restore$/.test(x.textContent.trim())); if(b) b.click(); return !!b;})()`);
await sleep(2500);
const rowsAfter = await session.eval(
  `[...document.querySelectorAll("[data-versions-list] [data-version-row]")].map(r=>({v:r.getAttribute("data-version-row"),current:!!r.querySelector("[data-version-current]")}))`,
);
const editorNodes = await session.eval(
  `[...document.querySelectorAll('[data-node-id]')].filter(n=>!n.closest('[data-version-preview]')).map(n=>n.getAttribute("data-node-id"))`,
);
const versionLabel = await session.eval(`(document.body.innerText.match(/\\bv5\\b/)||[])[0] ?? null`);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-versions.png", Buffer.from(shot.data, "base64"));

if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  created: Boolean(rule),
  versionsAfterSaves: listed.map((v) => `v${v.version}:${v.note}`),
  toggledVersion: toggled?.version,
  restoredVersion: restored?.version,
  versionsAfterRestore: afterRestore.map((v) => `v${v.version}${v.restored_from ? `<-v${v.restored_from}` : ""}`),
  v4Label: v4?.nodes?.[1]?.params?.label,
  openedTab,
  rows,
  previewNodes,
  dialogShown,
  confirmed,
  rowsAfter,
  editorNodes,
  versionLabel,
  screenshot: "/tmp/radd-versions.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  Boolean(rule) && Boolean(v2) && Boolean(v3) &&
  listed.length === 3 && listed[0].version === 3 && listed[2].note === "v1: the start" &&
  toggled?.version === 3 &&
  restored?.version === 4 &&
  afterRestore.length === 4 && afterRestore[0].restored_from === 1 &&
  v4?.nodes?.[1]?.params?.label === "one" &&
  openedTab &&
  rows.length === 4 && rows[0].v === "4" && rows[0].current && !rows[3].current &&
  previewNodes === 3 &&
  dialogShown &&
  confirmed &&
  rowsAfter.length === 5 && rowsAfter[0].v === "5" && rowsAfter[0].current &&
  editorNodes.length === 3 && editorNodes.includes("act2") &&
  versionLabel === "v5" &&
  consoleErrors.length === 0;
report({ "versions are written, browsed, previewed and restored": ok }, "RADD-1268 — versions");

close();
process.exit(ok ? 0 : 1);
