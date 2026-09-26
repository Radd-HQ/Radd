/**
 * Spec 116 / RADD-916: the node canvas actually draws a branching automation.
 *
 * Building is not verifying — a lazy chunk that 404s, a node view that never
 * mounts, or nodes stacked at 0x0 all produce a clean `tsc` and a clean build.
 * So this creates a real branching automation, opens it, and MEASURES the
 * result: node count, that the nodes occupy distinct non-zero boxes, that the
 * edge paths exist, and that both filter ports are drawn.
 *
 * Writes radd-canvas.png (lib/cdp outputPath) so the layout can be looked at, not just counted.
 *
 * Usage: node scripts/automations-canvas-proof.mjs [--base http://localhost:8000]
 */
import { outputPath, pageFetch, parsed, report, sleep } from "./lib/cdp.mjs";
import { openEditor } from "./lib/automation-editor.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9334, profile: "/tmp/radd-canvas-proof", base: "http://localhost:8000",
});

const branching = {
  name: "canvas proof (branching)",
  enabled: false,
  nodes: [
    { id: "trigger", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
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
const created = await session.eval(pageFetch("POST", "/automations", branching));
const rule = parsed(created);

await openEditor(session, baseUrl, branching.name);

let measured = null;
for (let i = 0; i < 40 && !measured; i++) {
  await sleep(500);
  measured = await session.eval(`(()=>{
    const nodes=[...document.querySelectorAll("[data-node-id]")];
    if(nodes.length===0) return null;
    const boxes=nodes.map(n=>{const r=n.getBoundingClientRect();
      return {id:n.getAttribute("data-node-id"),kind:n.getAttribute("data-node-kind"),
              x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};});
    const paths=[...document.querySelectorAll(".react-flow__edge-path")];
    // Geometry alone is NOT enough: these first shipped with correct path data
    // and an undefined colour token, so every edge was black on a dark canvas —
    // present, measurable, and invisible. Assert the resolved stroke too.
    // (No backticks in here: this whole block is a template literal.)
    const edges=paths.map(p=>{const cs=getComputedStyle(p);
      return {d:(p.getAttribute("d")||"").length, stroke:cs.stroke, width:cs.strokeWidth};});
    const black=["rgb(0, 0, 0)","rgba(0, 0, 0, 0)","none",""];
    // Orientation-agnostic: the default flow is VERTICAL, so source handles sit
    // on the bottom. Counting only the right-hand ones asserted the old default
    // and started failing the moment the default changed.
    const handles=[...document.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right")].length;
    return {boxes, edgeCount:edges.length,
            edgesHaveGeometry:edges.every(e=>e.d>10),
            edgesHaveVisibleStroke:edges.every(e=>!black.includes(e.stroke)),
            edgeStrokes:[...new Set(edges.map(e=>e.stroke))], handles};
  })()`);
}

const boxes = measured?.boxes ?? [];
const distinctPositions = new Set(boxes.map((b) => `${b.x},${b.y}`)).size;
const allVisible = boxes.every((b) => b.w > 40 && b.h > 20);

await session.screenshot(outputPath("radd-canvas.png"));

if (rule) await session.eval(pageFetch("DELETE", `/automations/${rule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  createStatus: created.status,
  nodesRendered: boxes.length,
  nodeKinds: boxes.map((b) => b.kind).sort(),
  distinctPositions,
  everyNodeHasSize: allVisible,
  edgeCount: measured?.edgeCount ?? 0,
  edgesHaveGeometry: measured?.edgesHaveGeometry ?? false,
  edgesHaveVisibleStroke: measured?.edgesHaveVisibleStroke ?? false,
  edgeStrokes: measured?.edgeStrokes ?? [],
  sourceHandlesDrawn: measured?.handles ?? 0,
  screenshot: outputPath("radd-canvas.png"),
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  created.status < 300 &&
  boxes.length === 4 &&
  distinctPositions === 4 && // stacked-at-0,0 is the classic silent layout failure
  allVisible &&
  (measured?.edgeCount ?? 0) === 3 &&
  measured?.edgesHaveGeometry &&
  measured?.edgesHaveVisibleStroke &&
  (measured?.handles ?? 0) >= 4 && // trigger 1 + filter 2 + two actions 1 each
  consoleErrors.length === 0;
report({ "node canvas draws a branching automation": ok }, "spec 116 phase 3");

close();
process.exit(ok ? 0 : 1);
