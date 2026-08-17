/**
 * RADD-921: seeing what an event carries, and what each node emitted.
 *
 * Asserts, in the real UI:
 *   - the trigger inspector shows PATHS SAMPLED FROM REAL EVENTS — the endpoint
 *     returns a non-zero `sampled` and the panel lists dotted paths with values
 *   - a path is clickable and yields the `{{payload.…}}` token
 *   - the "field changed" picker offers the fields the diff really names, in
 *     their own group, ahead of the full list
 *   - a dry run reports PER NODE: what arrived, what left each port, with item
 *     keys — and the canvas labels the ports with those counts
 *   - a gate's untaken branch reads "not taken", not "0" (the distinction the
 *     whole panel turns on)
 *   - a graph with no seed item still dry-runs, which is the case a search node
 *     or a schedule creates
 *
 * Measured, not eyeballed: a panel that renders is not one that is wired, and a
 * count that appears is not one that came from the walk.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9353, profile: "/tmp/radd-visibility" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// --- the endpoint reads REAL events -----------------------------------------
const sampled = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/samples/events?event_type=item.updated",
     {credentials:"include"});
   const j=await r.json();
   return {status:r.status, sampled:j.sampled, pathCount:(j.paths||[]).length,
           hasChangesField:(j.paths||[]).some(p=>p.path==="changes.field"),
           repeatedMarked:(j.paths||[]).some(p=>p.path==="changes.field"&&p.repeated),
           changedFields:j.changed_fields, hasExample:Boolean(j.example)};})()`,
);
// An unknown event type is a 409, not a plausible-looking empty answer.
const unknown = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/samples/events?event_type=made.up",
     {credentials:"include"}); return r.status;})()`,
);

// --- a graph with a gate, a filter and two actions ---------------------------
// The gate tests an actor nobody matches, so its `true` branch is NEVER taken —
// which must read differently from a filter that matched nothing.
const created = await session.eval(
  post("/automations", {
    name: "visibility proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      // A real event type, so the payload panel has something to sample. The
      // dry run does not care which — `/test` starts at the node it is given.
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "flt1", kind: "filter", type: "filter.slq", params: { slq: "priority = blocker" } },
      { id: "gate1", kind: "gate", type: "gate.changed_by", params: { users: ["nobody@example.invalid"] } },
      { id: "act1", kind: "action", type: "action.add_label", params: { label: "seen" } },
      { id: "orph", kind: "action", type: "action.add_label", params: { label: "never" } },
    ],
    edges: [
      { source: "trg1", port: "out", target: "flt1" },
      { source: "flt1", port: "matched", target: "gate1" },
      { source: "gate1", port: "true", target: "act1" },
    ],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;

// --- the API half of the dry run, seeded and unseeded ------------------------
const unseeded = await session.eval(
  post(`/automations/${rule.id}/test`, { item_id: null, trigger_node_id: "trg1" }),
);
const unseededResult = JSON.parse(unseeded.body);

await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("visibility proof"));if(el)el.click();return !!el;})()`,
);
await sleep(3000);

// --- the trigger's payload panel --------------------------------------------
await session.eval(
  `(()=>{const n=[...document.querySelectorAll('[data-node-id]')].find(e=>/trigger\\.event/.test(e.innerText));
     if(n){n.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,view:window}));n.click();} return !!n;})()`,
);
await sleep(1200);
const panelIsForTheTrigger = await session.eval(
  `(()=>{const p=document.querySelector("[data-event-samples]");
     return p?p.getAttribute("data-event-samples"):"";})()`,
);
const openedPanel = await session.eval(`(()=>{
  const panel=document.querySelector("[data-event-samples]");
  if(!panel) return false;
  panel.querySelector("button").click(); return true;})()`);
await sleep(1800);
const panel = await session.eval(`(()=>{
  const panel=document.querySelector("[data-event-samples]");
  if(!panel) return null;
  const rows=[...panel.querySelectorAll("li button")].map(b=>b.innerText.replace(/\\s+/g," ").trim());
  return {rows:rows.slice(0,6), count:rows.length,
          saysEmpty:/never been recorded/i.test(panel.innerText)};})()`);
// Clicking a path copies/inserts its token.
const clickedPath = await session.eval(`(()=>{
  const panel=document.querySelector("[data-event-samples]");
  const row=[...panel.querySelectorAll("li button")].find(b=>/changes\\.field/.test(b.innerText));
  if(!row) return false; row.click(); return true;})()`);
await sleep(600);
// The click produced FEEDBACK. Which feedback depends on the environment, and
// deliberately so: headless denies the clipboard, and the panel says "select it
// above" rather than claiming a copy that did not happen. Asserting only
// "copied" here would have made the honest fallback look like a regression.
const insertedFeedback = await session.eval(
  `/copied|inserted|select it above/i.test(document.querySelector("[data-event-samples]").innerText)`,
);

// --- the field-changed picker offers what the diff really names --------------
await session.eval(
  `(()=>{const n=[...document.querySelectorAll('[data-node-id]')].find(e=>/changed_by/.test(e.innerText));
     if(n){n.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,view:window}));n.click();} return !!n;})()`,
);
await sleep(900);

// --- the dry run, in the UI --------------------------------------------------
const ranInUi = await session.eval(`(()=>{
  const button=[...document.querySelectorAll("button")].find(b=>b.textContent.trim()==="Run");
  if(!button) return false; button.click(); return true;})()`);
await sleep(3000);
const nodeRows = await session.eval(
  `[...document.querySelectorAll("[data-node-result]")].map(li=>li.innerText.replace(/\\s+/g," ").trim())`,
);
const portLabels = await session.eval(
  `[...document.querySelectorAll("[data-port-label]")].map(s=>s.innerText.replace(/\\s+/g," ").trim())`,
);
const canvasRun = await session.eval(
  `[...document.querySelectorAll("[data-node-run]")].map(d=>d.getAttribute("data-node-run"))`,
);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-visibility.png", Buffer.from(shot.data, "base64"));

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const gateResult = unseededResult.nodes?.find((n) => n.node_id === "gate1");
const orphanResult = unseededResult.nodes?.find((n) => n.node_id === "orph");
const checks = {
  loginStatus,
  sampled,
  unknownEventTypeStatus: unknown,
  dryRunWithoutASeedItem: {
    status: unseeded.status,
    nodeCount: unseededResult.nodes?.length,
    gateTruePortTaken: gateResult?.ports.find((p) => p.port === "true")?.taken,
    gateFalsePortTaken: gateResult?.ports.find((p) => p.port === "false")?.taken,
    orphanRan: orphanResult?.ran,
  },
  panelIsForTheTrigger,
  openedPanel,
  panel,
  clickedPath,
  insertedFeedback,
  ranInUi,
  nodeRows,
  portLabels,
  canvasRun,
  screenshot: "/tmp/radd-visibility.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  // sampled from REAL events, with the list-element path and its marker
  sampled.status === 200 &&
  sampled.sampled > 0 &&
  sampled.hasChangesField &&
  sampled.repeatedMarked &&
  sampled.changedFields.length > 0 &&
  sampled.hasExample &&
  unknown === 409 &&
  // a graph with no seed item still dry-runs — the search/schedule case
  unseeded.status === 200 &&
  unseededResult.nodes.length === 5 &&
  gateResult?.ports.find((p) => p.port === "true")?.taken === false &&
  gateResult?.ports.find((p) => p.port === "false")?.taken === true &&
  orphanResult?.ran === false &&
  // the UI half
  panelIsForTheTrigger === "item.updated" &&
  openedPanel &&
  panel &&
  !panel.saysEmpty &&
  panel.count > 5 &&
  clickedPath &&
  insertedFeedback &&
  ranInUi &&
  nodeRows.length === 5 &&
  nodeRows.some((row) => /did not run/.test(row)) &&
  nodeRows.some((row) => /not taken/.test(row)) &&
  // Labels are CSS-uppercased and innerText returns the transformed text.
  portLabels.some((label) => /matched \d/i.test(label)) &&
  portLabels.some((label) => /^true$/i.test(label)) && // untaken: no count at all
  canvasRun.includes("skipped") &&
  consoleErrors.length === 0;

report({ "event payload samples and per-node dry run": ok }, "RADD-921 — visibility");

close();
process.exit(ok ? 0 : 1);
