/**
 * Spec 116 / RADD-916: a branching automation can be BUILT on the canvas,
 * without switching back to the form.
 *
 * This is the interaction the whole phase exists for, so it is driven through
 * the real UI rather than the API: open a linear automation, switch to Graph,
 * add a Filter and an Action from the palette, and check the palette actually
 * put them in the graph.
 *
 * The API-level branching proof lives in automations-graph-proof.mjs; this one
 * is about the affordances existing and working where a person clicks.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9337, profile: "/tmp/radd-canvas-edit" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// A plain LINEAR automation — the canvas has to be able to grow it into a
// branching one, which is the point.
const created = await session.eval(
  post("/automations", {
    name: "canvas edit proof",
    enabled: false,
    nodes: [
      { id: "trigger", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "a0", kind: "action", type: "action.add_label", params: { label: "seed" } },
    ],
    edges: [{ source: "trigger", port: "out", target: "a0" }],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;

await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("canvas edit proof"));` +
    `if(el) el.click(); return !!el;})()`,
);
await sleep(1500);

// Switch to the Graph tab.
// The graph IS the editor now — there is no Form/Graph switch to press.
const switched = true;
await sleep(2500);

const before = await session.eval(`document.querySelectorAll("[data-node-id]").length`);
// The node PANEL, not the old "Add node" toolbar text.
const paletteVisible = await session.eval(
  `!!document.querySelector('[data-node-panel] input[aria-label="Search nodes"]')`,
);

// Add a Filter, then an Action, from the node PANEL. (The old top palette bar
// this used to click was replaced by the side panel; clicking by bare label
// silently found nothing and the proof reported "added" as false.)
const addFromPanel = (term, re) =>
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    if(!i) return false;
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,${JSON.stringify(term)}); i.dispatchEvent(new Event("input",{bubbles:true}));
    return true;})()`;
const clickPanelRow = (re) =>
  `(()=>{const b=[...document.querySelectorAll("[data-node-panel] li button")]
     .find(n=>${re}.test(n.textContent)); if(b) b.click(); return !!b;})()`;

await session.eval(addFromPanel("filter items"));
await sleep(700);
const addedFilter = await session.eval(clickPanelRow("/filter items/i"));
await sleep(900);
await session.eval(addFromPanel("add label"));
await sleep(700);
const addedAction = await session.eval(clickPanelRow("/add label/i"));
await sleep(1200);

const after = await session.eval(`document.querySelectorAll("[data-node-id]").length`);
// Counting DOM nodes is NOT enough. A node placed outside the canvas bounds is
// in the DOM, measurable, and invisible — the first version stacked new nodes
// downward and the second one landed 5px past the bottom edge. Assert every
// node's box actually falls inside the canvas wrapper.
const allInsideCanvas = await session.eval(`(()=>{
  const wrap=document.querySelector(".react-flow");
  if(!wrap) return false;
  const w=wrap.getBoundingClientRect();
  return [...document.querySelectorAll("[data-node-id]")].every(n=>{
    const b=n.getBoundingClientRect();
    return b.top>=w.top-1 && b.bottom<=w.bottom+1 && b.left>=w.left-1 && b.right<=w.right+1;
  });
})()`);
const kinds = await session.eval(
  `[...document.querySelectorAll("[data-node-id]")].map(n=>n.getAttribute("data-node-kind")).sort()`,
);
// A node added but never wired must be called out, not left silently inert.
const warnsUnwired = await session.eval(`/never run/i.test(document.body.innerText)`);
// The inspector should be editing the node that was just added.
const inspectorOpen = await session.eval(
  `/Select a node to edit it/i.test(document.body.innerText) === false`,
);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-canvas-edit.png", Buffer.from(shot.data, "base64"));

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  createStatus: created.status,
  paletteVisible,
  nodesBefore: before,
  addedFilterButton: addedFilter,
  addedActionButton: addedAction,
  nodesAfter: after,
  everyNodeInsideCanvas: allInsideCanvas,
  kinds,
  warnsAboutUnwiredNodes: warnsUnwired,
  inspectorOpen,
  screenshot: "/tmp/radd-canvas-edit.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  paletteVisible &&
  before === 2 &&
  after === 4 && // seed 2 + filter + action
  allInsideCanvas && // in the DOM is not the same as on the screen
  warnsUnwired && // they arrive unwired, and that is said out loud
  inspectorOpen &&
  consoleErrors.length === 0;
report({ "nodes can be added on the canvas": ok }, "spec 116 phase 3 — editing");

close();
process.exit(ok ? 0 : 1);
