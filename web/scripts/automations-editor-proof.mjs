/**
 * Spec 116 / RADD-916: the automation editor is the canvas.
 *
 * Asserts what a front-end user actually needs:
 *   - opening an automation lands on the GRAPH (there is no form any more)
 *   - the node panel lists every category, triggers included, and searches
 *   - a TRIGGER can be added from the panel, and several can coexist
 *   - right-clicking empty canvas opens a searchable menu that adds a node
 *   - orientation flips vertical <-> horizontal and the ports move with it
 *   - every node is inside the canvas, visible, with coloured edges
 *
 * Measured, not eyeballed: presence in the DOM is not visibility, which is the
 * lesson from this feature's first three attempts.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9340, profile: "/tmp/radd-editor-proof" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

const clickText = (text) =>
  `(()=>{const b=[...document.querySelectorAll("button")].find(n=>n.textContent.trim()===${JSON.stringify(text)});` +
  `if(b) b.click(); return !!b;})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// A graph with TWO triggers — the thing a single column could not hold.
const created = await session.eval(
  post("/automations", {
    name: "editor proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.created" } },
      { id: "trg2", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "act1", kind: "action", type: "action.add_label", params: { label: "seen" } },
    ],
    edges: [
      { source: "trg1", port: "out", target: "act1" },
      { source: "trg2", port: "out", target: "act1" },
    ],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;
const triggersBack = rule ? rule.triggers.map((t) => t.event_type).sort() : [];

await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("editor proof"));if(el)el.click();return !!el;})()`,
);
await sleep(3000);

// The canvas is the editor — no Form tab to switch to.
const noFormTab = await session.eval(
  `![...document.querySelectorAll("button")].some(b=>b.textContent.trim()==="Form")`,
);
const panelGroups = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] button[aria-expanded]")].map(b=>b.textContent.replace(/\\d+$/,"").trim())`,
);
const hasTriggerGroup = panelGroups.some((g) => /^Triggers/.test(g));

// Search the panel.
await session.eval(
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    if(!i) return false;
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,"webhook");
    i.dispatchEvent(new Event("input",{bubbles:true}));
    return true;})()`,
);
await sleep(700);
const searchHits = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] li button")].map(b=>b.textContent.trim())`,
);

// Clear the search, then add a THIRD trigger from the panel.
await session.eval(
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,"schedule"); i.dispatchEvent(new Event("input",{bubbles:true})); return true;})()`,
);
await sleep(700);
const addedTrigger = await session.eval(
  `(()=>{const b=[...document.querySelectorAll("[data-node-panel] li button")].find(n=>/on a schedule/i.test(n.textContent));
    if(b) b.click(); return !!b;})()`,
);
await sleep(1200);
const triggerNodesOnCanvas = await session.eval(
  `document.querySelectorAll('[data-node-kind="trigger"]').length`,
);

// Right-click the canvas -> searchable menu.
const menuOpened = await session.eval(`(()=>{
  const pane=document.querySelector(".react-flow__pane");
  if(!pane) return false;
  const r=pane.getBoundingClientRect();
  pane.dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,cancelable:true,
    clientX:Math.round(r.x+r.width*0.6), clientY:Math.round(r.y+r.height*0.6)}));
  return true;})()`);
await sleep(800);
const menuVisible = await session.eval(`!!document.querySelector("[data-node-menu]")`);
const addedFromMenu = await session.eval(`(()=>{
  const menu=document.querySelector("[data-node-menu]");
  if(!menu) return false;
  const i=menu.querySelector("input");
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
  setter.call(i,"comment"); i.dispatchEvent(new Event("input",{bubbles:true}));
  return true;})()`);
await sleep(600);
const menuHits = await session.eval(
  `[...document.querySelectorAll("[data-node-menu] li button")].map(b=>b.textContent.trim()).slice(0,4)`,
);
await session.eval(
  `(()=>{const b=document.querySelector("[data-node-menu] li button"); if(b) b.click(); return !!b;})()`,
);
await sleep(1200);
const nodesAfterMenu = await session.eval(`document.querySelectorAll("[data-node-id]").length`);

// Orientation: vertical puts source handles on the BOTTOM.
const verticalPorts = await session.eval(
  `document.querySelectorAll(".react-flow__handle-bottom").length`,
);
await session.eval(clickText("Horizontal"));
await sleep(1500);
const horizontalPorts = await session.eval(
  `document.querySelectorAll(".react-flow__handle-right").length`,
);

const visuals = await session.eval(`(()=>{
  const wrap=document.querySelector(".react-flow");
  const w=wrap.getBoundingClientRect();
  const nodes=[...document.querySelectorAll("[data-node-id]")];
  const inside=nodes.every(n=>{const b=n.getBoundingClientRect();
    return b.top>=w.top-1&&b.bottom<=w.bottom+1&&b.left>=w.left-1&&b.right<=w.right+1;});
  const visible=nodes.every(n=>getComputedStyle(n.closest(".react-flow__node")).visibility==="visible");
  // Overlap: two nodes sharing screen space read as one node, which is how the
  // first pass placed a new trigger exactly on top of an auto-laid-out one.
  let overlapping=false;
  for(let i=0;i<nodes.length;i++){for(let j=i+1;j<nodes.length;j++){
    const a=nodes[i].getBoundingClientRect(), b=nodes[j].getBoundingClientRect();
    if(a.left<b.right-4&&b.left<a.right-4&&a.top<b.bottom-4&&b.top<a.bottom-4) overlapping=true;}}
  const strokes=[...document.querySelectorAll(".react-flow__edge-path")].map(p=>getComputedStyle(p).stroke);
  const black=["rgb(0, 0, 0)","rgba(0, 0, 0, 0)","none",""];
  const staleFormCopy=/Form tab/i.test(document.body.innerText);
  return {inside, visible, overlapping, staleFormCopy, edgeCount:strokes.length, strokesVisible:strokes.every(s=>!black.includes(s))};
})()`);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-editor.png", Buffer.from(shot.data, "base64"));

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  createStatus: created.status,
  twoTriggersStored: triggersBack,
  graphIsTheOnlyEditor: noFormTab,
  panelGroupCount: panelGroups.length,
  panelHasTriggerGroups: hasTriggerGroup,
  panelSearchHits: searchHits,
  addedTriggerFromPanel: addedTrigger,
  triggerNodesOnCanvas,
  rightClickMenuOpened: menuVisible && menuOpened && addedFromMenu,
  menuSearchHits: menuHits,
  nodesAfterMenuAdd: nodesAfterMenu,
  bottomHandlesWhenVertical: verticalPorts,
  rightHandlesWhenHorizontal: horizontalPorts,
  ...visuals,
  screenshot: "/tmp/radd-editor.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  created.status < 300 &&
  triggersBack.length === 2 &&
  noFormTab &&
  hasTriggerGroup &&
  searchHits.length > 0 &&
  addedTrigger &&
  triggerNodesOnCanvas === 3 && // two seeded + one added from the panel
  menuVisible &&
  menuHits.length > 0 &&
  nodesAfterMenu === 5 &&
  verticalPorts > 0 &&
  horizontalPorts > 0 &&
  visuals.inside &&
  visuals.visible &&
  visuals.strokesVisible &&
  !visuals.overlapping &&
  !visuals.staleFormCopy &&
  consoleErrors.length === 0;
report({ "the canvas is the automation editor": ok }, "spec 116 — editor");

close();
process.exit(ok ? 0 : 1);
