/**
 * Run history (RADD-1266) — a real run leaves a row, and the editor shows it.
 *
 * The engine used to keep nothing of a run but a log line. This proves, against
 * a running server and its consumer loop:
 *
 *   - an item update fires an enabled automation and the run is RECORDED with
 *     status, source, the item's key and the action counts;
 *   - the automations list carries the newest run's chip;
 *   - the editor's Runs tab lists it, opening a run renders the same per-node
 *     report the dry run does, and the canvas labels its ports from it;
 *   - a skipped action reads as "nothing to do" with its reason kept.
 *
 * Usage: node scripts/automations-runs-proof.mjs [--base http://localhost:8000]
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9357, profile: "/tmp/radd-runs" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`}});` +
  `return {status:r.status, body: await r.text()};})()`;
const parsed = (r) => (r.status < 300 ? JSON.parse(r.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// --- fixtures: a project, an item, an automation that labels it on update ----
const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
const project = parsed(await session.eval(api("POST", "/projects", { key: `RH${suffix}`, name: `Runs ${suffix}` })));
const item = parsed(
  await session.eval(api("POST", "/items", { project_id: project?.id, title: "Runs proof item" })),
);
const created = await session.eval(
  api("POST", "/automations", {
    name: `runs proof ${suffix}`,
    enabled: true,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "flt1", kind: "filter", type: "filter.slq", params: { slq: `project = ${project?.key}` } },
      { id: "act1", kind: "action", type: "action.add_label", params: { label: "seen-by-runs-proof" } },
      // A target nobody has: the planner SKIPS it, and the run must say why.
      { id: "act2", kind: "action", type: "action.set_assignee", params: { assignee: "nobody@example.invalid" } },
    ],
    edges: [
      { source: "trg1", port: "out", target: "flt1" },
      { source: "flt1", port: "matched", target: "act1" },
      { source: "flt1", port: "matched", target: "act2" },
    ],
  }),
);
const rule = parsed(created);

// --- fire it: an update the consumer will pick up ---------------------------
const updated = await session.eval(api("PATCH", `/items/${item?.id}`, { title: "Runs proof item, renamed" }));
// The consumer polls every second; give it a few.
let runs = [];
for (let attempt = 0; attempt < 12 && runs.length === 0; attempt++) {
  await sleep(1000);
  runs = parsed(await session.eval(api("GET", `/automations/${rule?.id}/runs`))) ?? [];
}
const run = runs[0] ?? null;
const detail = run ? parsed(await session.eval(api("GET", `/automations/${rule?.id}/runs/${run.id}`))) : null;
const itemAfter = parsed(await session.eval(api("GET", `/items/${item?.id}`)));
const skipped = detail?.report?.would_apply?.find((a) => a.node_id === "act2") ?? null;
const applied = detail?.report?.would_apply?.find((a) => a.node_id === "act1") ?? null;

// --- the list shows the newest run ------------------------------------------
await session.navigate(`${baseUrl}/settings/automations`, 2500);
const listChip = await session.eval(
  `(()=>{const li=[...document.querySelectorAll("li")].find(l=>l.innerText.includes(${JSON.stringify(`runs proof ${suffix}`)}));
     const chip=li&&li.querySelector("[data-last-run] [data-run-status]");
     return chip?chip.getAttribute("data-run-status"):null;})()`,
);

// --- the editor's Runs tab ---------------------------------------------------
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes(${JSON.stringify(`runs proof ${suffix}`)}));if(el)el.click();return !!el;})()`,
);
await sleep(2500);
const openedTab = await session.eval(
  `(()=>{const tab=[...document.querySelectorAll('[role="tab"]')].find(t=>/^Runs$/.test(t.textContent.trim()));
     if(!tab) return false; tab.click(); return true;})()`,
);
await sleep(1500);
const rowCount = await session.eval(`document.querySelectorAll("[data-runs-list] [data-run-row]").length`);
const rowText = await session.eval(
  `(document.querySelector("[data-runs-list] [data-run-row]")||{innerText:""}).innerText.replace(/\\s+/g," ").trim()`,
);
await session.eval(`(()=>{const b=document.querySelector("[data-runs-list] [data-run-row]"); if(b) b.click(); return !!b;})()`);
await sleep(1800);
const nodeRows = await session.eval(
  `[...document.querySelectorAll("[data-run-result] [data-node-result]")].map(li=>li.innerText.replace(/\\s+/g," ").trim())`,
);
const actionRows = await session.eval(
  `[...document.querySelectorAll("[data-run-result] [data-action-preview]")].map(li=>({node:li.getAttribute("data-action-preview"),text:li.innerText.replace(/\\s+/g," ").trim()}))`,
);
const canvasRun = await session.eval(
  `[...document.querySelectorAll("[data-node-run]")].map(d=>d.getAttribute("data-node-run"))`,
);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-runs.png", Buffer.from(shot.data, "base64"));

// --- cleanup -----------------------------------------------------------------
if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));
if (item) await session.eval(api("DELETE", `/items/${item.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  fixtures: { project: project?.key, item: item?.key, rule: rule?.id, updated: updated.status },
  run: run && { status: run.status, source: run.source, event_type: run.event_type, item_keys: run.item_keys, applied: run.actions_applied, skipped: run.actions_skipped },
  labelLanded: Boolean(itemAfter?.labels?.includes("seen-by-runs-proof")),
  appliedAction: applied && { resolves: applied.resolves, detail: applied.detail },
  skippedAction: skipped && { resolves: skipped.resolves, detail: skipped.detail },
  reportNodes: detail?.report?.nodes?.map((n) => `${n.node_id}:${n.ran}`),
  listChip,
  openedTab,
  rowCount,
  rowText,
  nodeRows,
  actionRows,
  canvasRun,
  screenshot: "/tmp/radd-runs.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  Boolean(rule) &&
  updated.status < 300 &&
  run?.status === "applied" &&
  run?.source === "event" &&
  run?.event_type === "item.updated" &&
  run?.item_keys?.[0] === item?.key &&
  run?.actions_applied === 1 &&
  run?.actions_skipped === 1 &&
  checks.labelLanded &&
  applied?.resolves === true &&
  skipped?.resolves === false &&
  /no user/.test(skipped?.detail ?? "") &&
  (checks.reportNodes ?? []).length === 4 &&
  listChip === "applied" &&
  openedTab &&
  rowCount >= 1 &&
  /Applied/i.test(rowText) &&
  rowText.includes(item?.key ?? "—") &&
  nodeRows.length === 4 &&
  actionRows.length === 2 &&
  actionRows.some((a) => a.node === "act1" && /^Applied/i.test(a.text)) &&
  actionRows.some((a) => a.node === "act2" && /Skipped/i.test(a.text) && /no user/.test(a.text)) &&
  canvasRun.filter((v) => v === "ran").length === 4 &&
  consoleErrors.length === 0;
report({ "a real run is recorded and readable in the editor": ok }, "RADD-1266 — run history");

close();
process.exit(ok ? 0 : 1);
