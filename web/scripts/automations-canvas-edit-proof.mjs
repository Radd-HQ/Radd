/**
 * Spec 116 / RADD-916: nodes added from the node panel land inside the canvas, arrive unwired
 * (and say so), and open in the inspector.
 */
import { outputPath, pageFetch, parsed, report, sleep } from "./lib/cdp.mjs";
import { clickPanelRow, openEditor, searchNodes } from "./lib/automation-editor.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9337, profile: "/tmp/radd-canvas-edit", base: "http://localhost:8000",
});

// A plain LINEAR automation — the canvas has to be able to grow it into a
// branching one, which is the point.
const created = await session.eval(
  pageFetch("POST", "/automations", {
    name: "canvas edit proof",
    enabled: false,
    nodes: [
      { id: "trigger", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "a0", kind: "action", type: "action.add_label", params: { label: "seed" } },
    ],
    edges: [{ source: "trigger", port: "out", target: "a0" }],
  }),
);
const rule = parsed(created);

await openEditor(session, baseUrl, "canvas edit proof");
await sleep(1500);

const before = await session.eval(`document.querySelectorAll("[data-node-id]").length`);
// The node PANEL, not the old "Add node" toolbar text.
const paletteVisible = await session.eval(
  `!!document.querySelector('[data-node-panel] input[aria-label="Search nodes"]')`,
);

// Add a Filter, then an Action, from the node PANEL. (The old top palette bar
// this used to click was replaced by the side panel; clicking by bare label
// silently found nothing and the proof reported "added" as false.)
await session.eval(searchNodes("filter issues"));
await sleep(700);
const addedFilter = await session.eval(clickPanelRow(/filter issues/i));
await sleep(900);
await session.eval(searchNodes("add label"));
await sleep(700);
const addedAction = await session.eval(clickPanelRow(/add label/i));
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

await session.screenshot(outputPath("radd-canvas-edit.png"));

if (rule) await session.eval(pageFetch("DELETE", `/automations/${rule.id}`));

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
  screenshot: outputPath("radd-canvas-edit.png"),
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
