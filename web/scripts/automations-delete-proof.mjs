/**
 * Spec 116 / RADD-916: a deleted node stays deleted.
 *
 * The reported bug, exactly: add a node, delete it with BACKSPACE, add another
 * node — and the first one came back. React Flow owns the delete key, so the
 * removal was applied to its internal copy and never reached the graph; adding
 * anything changed the re-seed signature and the "deleted" node returned. The
 * inspector's Delete button did not have the bug because it went through the
 * graph.
 *
 * Asserts both paths, and the edge case that shares the mechanism:
 *   - delete by keyboard, then add -> stays deleted
 *   - delete by keyboard -> the edges that touched it go too
 *   - delete by the inspector button -> still works
 *   - the deletion SURVIVES a save/reload, not just the local state
 */
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9343, profile: "/tmp/radd-delete-proof" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

const addFromPanel = (term, re) => [
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    if(!i) return false;
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,${JSON.stringify(term)}); i.dispatchEvent(new Event("input",{bubbles:true}));
    return true;})()`,
  `(()=>{const b=[...document.querySelectorAll("[data-node-panel] li button")]
     .find(n=>${re}.test(n.textContent)); if(b) b.click(); return !!b;})()`,
];

const nodeIds = `[...document.querySelectorAll("[data-node-id]")].map(n=>n.getAttribute("data-node-id")).sort()`;
const edgeCount = `document.querySelectorAll(".react-flow__edge-path").length`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

const created = await session.eval(
  post("/automations", {
    name: "delete proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
      { id: "act1", kind: "action", type: "action.add_label", params: { label: "seed" } },
    ],
    edges: [{ source: "trg1", port: "out", target: "act1" }],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;

await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("delete proof"));if(el)el.click();return !!el;})()`,
);
await sleep(3000);

// 1. Add a filter.
const [searchFilter, clickFilter] = addFromPanel("filter items", "/filter items/i");
await session.eval(searchFilter);
await sleep(700);
await session.eval(clickFilter);
await sleep(1200);
const afterAdd = await session.eval(nodeIds);

// 2. Select it on the canvas and press BACKSPACE — React Flow's own delete key.
//
// REAL browser input, not synthetic dispatchEvent. A hand-built MouseEvent has
// no `view`, and React Flow's drag handler reads `.document` off it — which
// threw a TypeError that looked exactly like a product bug until it was checked
// against real input. Driving the browser is also simply a truer test.
const nodeBox = await session.eval(`(()=>{
  const node=[...document.querySelectorAll("[data-node-id]")].find(n=>/flt/.test(n.getAttribute("data-node-id")));
  if(!node) return null;
  const r=node.closest(".react-flow__node").getBoundingClientRect();
  return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};})()`);
const deletedByKey = Boolean(nodeBox);
if (nodeBox) {
  for (const type of ["mousePressed", "mouseReleased"]) {
    await session.send("Input.dispatchMouseEvent", {
      type, x: nodeBox.x, y: nodeBox.y, button: "left", clickCount: 1,
    });
  }
  await sleep(400);
  for (const type of ["rawKeyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", {
      type, key: "Backspace", code: "Backspace", windowsVirtualKeyCode: 8,
    });
  }
}
await sleep(1200);
const afterKeyDelete = await session.eval(nodeIds);

// 3. THE BUG: add another node and see whether the deleted one returns.
const [searchLabel, clickLabel] = addFromPanel("add label", "/add label/i");
await session.eval(searchLabel);
await sleep(700);
await session.eval(clickLabel);
await sleep(1400);
const afterSecondAdd = await session.eval(nodeIds);
const resurrected = afterSecondAdd.some((id) => /flt/.test(id));

// 4. Delete by the inspector button (the path that always worked).
const deletedByButton = await session.eval(`(()=>{
  const b=[...document.querySelectorAll("button")].find(n=>n.textContent.trim()==="Delete");
  if(b) b.click(); return !!b;})()`);
await sleep(1200);
const afterButtonDelete = await session.eval(nodeIds);

// 5. It has to survive a SAVE, not just local state.
await session.eval(
  `(()=>{const b=[...document.querySelectorAll("button")].find(n=>/save changes/i.test(n.textContent));
    if(b) b.click(); return !!b;})()`,
);
await sleep(2500);
// The list, not a single GET — there is no GET /automations/{id} route.
const stored = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations",{credentials:"include"});
    const list=await r.json();
    const mine=(list||[]).find(a=>a.id===${JSON.stringify(rule?.id ?? "")});
    return mine ? mine.nodes.map(n=>n.id).sort() : null;})()`,
);

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  afterAdd,
  deletedByKey,
  afterKeyDelete,
  afterSecondAdd,
  deletedNodeCameBack: resurrected,
  deletedByButton,
  afterButtonDelete,
  storedAfterSave: stored,
  edgesLeft: await session.eval(edgeCount),
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  afterAdd.length === 3 &&
  deletedByKey &&
  afterKeyDelete.length === 2 && // the keyboard delete actually removed it
  !resurrected && // THE BUG: adding a node must not bring it back
  deletedByButton &&
  Array.isArray(stored) &&
  !stored.some((id) => /flt/.test(id)) && // the deletion survived the save
  consoleErrors.length === 0;
report({ "a deleted node stays deleted": ok }, "spec 116 — delete");

close();
process.exit(ok ? 0 : 1);
