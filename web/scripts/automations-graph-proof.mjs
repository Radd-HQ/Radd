/**
 * Spec 116 / RADD-914: the automations settings page still works after the
 * three pipeline columns became a graph.
 *
 * Phase 1 is deliberately invisible — the list editor is unchanged, it just
 * speaks nodes/edges now. That is exactly the kind of change a clean `tsc`
 * cannot verify: the SPA's types are hand-written and have no idea the server
 * moved, so the only honest check is loading the page and saving a real rule
 * (the RADD-701 lesson — a wire constant is a contract with no compiler).
 *
 * Asserts:
 *   - the automations settings page renders (no white screen)
 *   - a linear rule round-trips and comes back as a graph with its action node
 *   - a BRANCHING graph is accepted and keeps both of its ports
 *   - no console errors along the way
 *
 * Usage: node scripts/automations-graph-proof.mjs [--base http://localhost:8000]
 */
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "hussein@hjarrar.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9333, profile: "/tmp/radd-automations-proof" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

await session.navigate(`${baseUrl}/settings/automations`, 1000);
let pageRendered = false;
for (let i = 0; i < 40 && !pageRendered; i++) {
  await sleep(500);
  pageRendered = await session.eval(
    `!!document.querySelector("main") && /automation/i.test(document.body.innerText)`,
  );
}

const linear = {
  name: "proof linear",
  enabled: false,
  nodes: [
    { id: "trigger", kind: "trigger", type: "trigger.event", params: { event: "item.created" } },
    { id: "a0", kind: "action", type: "action.add_label", params: { label: "proof" } },
  ],
  edges: [{ source: "trigger", port: "out", target: "a0" }],
};
const created = await session.eval(post("/automations", linear));
const createdBody = created.status < 300 ? JSON.parse(created.body) : null;
const actionNodesBack = createdBody ? createdBody.nodes.filter((n) => n.kind === "action").length : -1;

const branching = {
  name: "proof branching",
  enabled: false,
  nodes: [
    { id: "trigger", kind: "trigger", type: "trigger.event", params: { event: "item.created" } },
    { id: "f", kind: "filter", type: "filter.slq", params: { slq: "priority = high" } },
    { id: "hot", kind: "action", type: "action.add_label", params: { label: "urgent" } },
    { id: "cold", kind: "action", type: "action.add_comment", params: { body: "routine" } },
  ],
  edges: [
    { source: "trigger", port: "out", target: "f" },
    { source: "f", port: "matched", target: "hot" },
    { source: "f", port: "unmatched", target: "cold" },
  ],
};
const branched = await session.eval(post("/automations", branching));
const branchedBody = branched.status < 300 ? JSON.parse(branched.body) : null;
const forkedPorts = branchedBody
  ? new Set(branchedBody.edges.filter((e) => e.source === "f").map((e) => e.port)).size
  : -1;

// The list page must still render with a branching automation in it — this is
// where a naive `rule.actions.length` would have thrown a white screen.
await session.navigate(`${baseUrl}/settings/automations`, 1500);
const stillRenders = await session.eval(
  `!!document.querySelector("main") && /proof branching/i.test(document.body.innerText)`,
);

for (const made of [createdBody, branchedBody]) {
  if (made) {
    await session.eval(
      `fetch("/api/v1/automations/${made.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
    );
  }
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  automationsPageRendered: pageRendered,
  linearCreateStatus: created.status,
  actionNodesRoundTripped: actionNodesBack,
  branchingCreateStatus: branched.status,
  branchingKeptBothPorts: forkedPorts,
  listRendersWithBranchingRule: stillRenders,
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  pageRendered &&
  created.status < 300 &&
  actionNodesBack === 1 &&
  branched.status < 300 &&
  forkedPorts === 2 &&
  stillRenders &&
  consoleErrors.length === 0;
report({ "automations graph (spec 116)": ok }, "spec 116 phase 1");

close();
process.exit(ok ? 0 : 1);
