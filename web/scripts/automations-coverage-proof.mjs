/**
 * Coverage (RADD-1267) — every new node is offered, saves, and has a form.
 *
 * Proves, against a running server:
 *   - the palette lists the twelve new item actions, the project gate, and the
 *     pages plugin's two contributed actions;
 *   - a graph holding one of each saves (the server's action union accepts
 *     them all) and dry-runs without a server error;
 *   - selecting each on the canvas renders a form with at least one control;
 *   - the switched-on triggers appear in the trigger catalogue.
 *
 * Usage: node scripts/automations-coverage-proof.mjs [--base http://localhost:8000]
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9358, profile: "/tmp/radd-coverage" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`}});` +
  `return {status:r.status, body: await r.text()};})()`;
const parsed = (r) => (r.status < 300 ? JSON.parse(r.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

const catalog = parsed(await session.eval(api("GET", "/automations/catalog")));
const triggerTypes = new Set((catalog?.triggers ?? []).map((t) => t.event_type));
const contributed = new Set((catalog?.contributed_nodes ?? []).map((n) => n.key));

const NEW_ACTIONS = [
  ["set_parent", { parent: "none" }],
  ["set_type", { type: "Bug" }],
  ["set_reporter", { reporter: email }],
  ["set_dates", { start: "today", target: "today+7d" }],
  ["set_estimate", { points: "3" }],
  ["set_flag", { flagged: true }],
  ["set_visibility", { visibility: "internal" }],
  ["link_item", { target: "TD-1", link_type: "relates" }],
  ["archive_item", { archived: false }],
  ["add_watcher", { user: "reporter" }],
  ["add_participant", { user: "reporter" }],
  ["move_to_project", { project: "TD" }],
];

const nodes = [
  { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
  { id: "gate1", kind: "gate", type: "gate.project", params: { projects: ["TD"], negate: false } },
  ...NEW_ACTIONS.map(([type, params], index) => ({
    id: `act${index + 1}`, kind: "action", type: `action.${type}`, params,
  })),
];
// A CHAIN rather than a fan-out: twelve actions side by side lay out wider
// than the canvas, and React Flow only mounts what is in view — so the proof
// could not click them. In series they stack, and one fit-view shows all.
const edges = [
  { source: "trg1", port: "out", target: "gate1" },
  { source: "gate1", port: "true", target: "act1" },
  ...NEW_ACTIONS.slice(1).map((_, index) => ({ source: `act${index + 1}`, port: "out", target: `act${index + 2}` })),
];
const suffix = Math.random().toString(36).slice(2, 6);
const created = await session.eval(api("POST", "/automations", { name: `coverage proof ${suffix}`, enabled: false, orientation: "vertical", nodes, edges }));
const rule = parsed(created);
const dry = rule ? await session.eval(api("POST", `/automations/${rule.id}/test`, { item_id: null, trigger_node_id: null })) : { status: 0 };

// The pages plugin's nodes save on a page trigger.
const pageRule = parsed(await session.eval(api("POST", "/automations", {
  name: `coverage pages ${suffix}`, enabled: false, orientation: "vertical",
  nodes: [
    { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "page.updated" } },
    { id: "c1", kind: "action", type: "page.comment", params: { body: "Reviewed by automation", visibility: "public" } },
    { id: "m1", kind: "action", type: "page.move", params: { parent: "" } },
  ],
  edges: [{ source: "trg1", port: "out", target: "c1" }, { source: "c1", port: "out", target: "m1" }],
})));

// --- the palette and the forms ----------------------------------------------
await session.navigate(`${baseUrl}/settings/automations`, 2500);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes(${JSON.stringify(`coverage proof ${suffix}`)}));if(el)el.click();return !!el;})()`,
);
await sleep(2500);
const paletteRows = await session.eval(`(()=>{
  const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
  setter.call(i,""); i.dispatchEvent(new Event("input",{bubbles:true}));
  for (const b of document.querySelectorAll('[data-node-panel] button[aria-expanded="false"]')) b.click();
  return [...document.querySelectorAll("[data-node-panel] li button")].map(b=>b.textContent.trim());})()`);

await session.eval(`(()=>{const b=document.querySelector(".react-flow__controls-fitview"); if(b) b.click(); return !!b;})()`);
await sleep(800);
const mounted = await session.eval(`document.querySelectorAll("[data-node-id]").length`);
const forms = {};
for (const node of nodes.slice(1)) {
  await session.click(`[data-node-id="${node.id}"]`, () => true);
  await sleep(500);
  forms[node.type] = await session.eval(
    `document.querySelectorAll("form input, form select, form textarea, form [role=radiogroup], form [role=listbox]").length`,
  );
}
const titles = await session.eval(
  `[...document.querySelectorAll("[data-node-id] .text-heading")].map(e=>e.textContent.trim())`,
);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-coverage.png", Buffer.from(shot.data, "base64"));

if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));
if (pageRule) await session.eval(api("DELETE", `/automations/${pageRule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const wantedLabels = [
  "Project is", "Set parent", "Set issue type", "Set reporter", "Set dates", "Set estimate",
  "Flag / unflag", "Set visibility", "Link to item", "Archive / restore", "Add watcher",
  "Add participant", "Move to project", "Comment on the page", "Move the page",
];
const missingLabels = wantedLabels.filter((label) => !paletteRows.includes(label));
const wantedTriggers = [
  "user.created", "user.updated", "worklog.estimate_changed", "access.granted", "access.revoked",
  "page_space.public_access_changed", "sla_policy.created", "sla_policy.updated", "sla_policy.deleted",
];
const missingTriggers = wantedTriggers.filter((t) => !triggerTypes.has(t));
const formless = Object.entries(forms).filter(([, count]) => count === 0).map(([type]) => type);

const checks = {
  loginStatus,
  createdStatus: created.status,
  dryRunStatus: dry.status,
  pageRuleSaved: Boolean(pageRule),
  contributedPageNodes: ["page.comment", "page.move"].filter((k) => contributed.has(k)),
  missingLabels,
  missingTriggers,
  mounted,
  forms,
  formless,
  titles,
  screenshot: "/tmp/radd-coverage.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  created.status === 201 &&
  dry.status === 200 &&
  Boolean(pageRule) &&
  checks.contributedPageNodes.length === 2 &&
  missingLabels.length === 0 &&
  missingTriggers.length === 0 &&
  formless.length === 0 &&
  titles.includes("Project is") &&
  titles.includes("Move to project") &&
  consoleErrors.length === 0;
report({ "every new node is offered, saves, and has a form": ok }, "RADD-1267 — coverage");

close();
process.exit(ok ? 0 : 1);
