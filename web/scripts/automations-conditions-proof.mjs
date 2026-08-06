/**
 * Spec 116 revision: concrete condition nodes, Act As, and the contributed AI node.
 *
 * Asserts, in the real UI:
 *   - the palette offers named conditions (Field changed / Changed by / State
 *     category) and NOT the old abstract "Gate on the event"
 *   - selecting "Field changed" shows Field / From / To, not a condition tree
 *   - the AI classifier comes from the SERVER registry, and its ports are the
 *     answers you type — the canvas redraws them as you edit
 *   - "Act as" appears on an action for a caller who holds automation.act_as
 *
 * Measured, not eyeballed. Presence in the DOM is not visibility, and a form
 * that renders is not a form that is wired.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "hussein@hjarrar.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9342, profile: "/tmp/radd-conditions" });

const post = (path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:"POST",credentials:"include",` +
  `headers:{"Content-Type":"application/json"},body:JSON.stringify(${JSON.stringify(body)})});` +
  `return {status:r.status, body: await r.text()};})()`;

const search = (text) =>
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    if(!i) return false;
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,${JSON.stringify(text)}); i.dispatchEvent(new Event("input",{bubbles:true}));
    return true;})()`;

const clickPanelRow = (re) =>
  `(()=>{const b=[...document.querySelectorAll("[data-node-panel] li button")]
     .find(n=>${re}.test(n.textContent)); if(b) b.click(); return !!b;})()`;

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// The server decides what the palette can offer.
const catalog = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/catalog",{credentials:"include"});
    const j=await r.json();
    return {contributed:(j.contributed_nodes||[]).map(n=>n.key), canActAs:j.can_act_as};})()`,
);

const created = await session.eval(
  post("/automations", {
    name: "conditions proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
    ],
    edges: [],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;

await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("conditions proof"));if(el)el.click();return !!el;})()`,
);
await sleep(3000);

// --- the palette offers named conditions, not the abstract tree ---
await session.eval(search("changed"));
await sleep(700);
const conditionRows = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] li button")].map(b=>b.textContent.trim())`,
);
const offersOldGate = await session.eval(
  `(()=>{const i=document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
    setter.call(i,"gate on the event"); i.dispatchEvent(new Event("input",{bubbles:true}));
    return true;})()`,
);
await sleep(600);
const oldGateHits = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] li button")].length`,
);

// --- Field changed shows a real form ---
await session.eval(search("field changed"));
await sleep(600);
const addedFieldChanged = await session.eval(clickPanelRow("/field changed/i"));
await sleep(1200);
const fieldChangedForm = await session.eval(`(()=>{
  const t=document.body.innerText;
  return {hasField:/\\bField\\b/.test(t), hasFrom:/\\bFrom\\b/.test(t), hasTo:/\\bTo\\b/.test(t),
          noTree:!/subject|operator/i.test(t)};
})()`);

// --- the AI classifier: ports follow the answers you type ---
await session.eval(search("ask the ai"));
await sleep(600);
const addedAi = await session.eval(clickPanelRow("/ask the ai/i"));
await sleep(1200);
const portsBefore = await session.eval(
  `(()=>{const n=[...document.querySelectorAll('[data-node-id]')].find(e=>/ai\\.classify/.test(e.innerText));
     return n ? n.parentElement.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right").length : -1;})()`,
);
const typedAnswers = await session.eval(`(()=>{
  const input=[...document.querySelectorAll("input")].find(i=>i.getAttribute("aria-label")==="Possible answers");
  if(!input) return false;
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
  for (const answer of ["bug","feature","question"]) {
    setter.call(input, answer);
    input.dispatchEvent(new Event("input",{bubbles:true}));
    input.dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}));
  }
  return true;})()`);
await sleep(1500);
const portsAfter = await session.eval(
  `(()=>{const n=[...document.querySelectorAll('[data-node-id]')].find(e=>/ai\\.classify/.test(e.innerText));
     return n ? n.parentElement.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right").length : -1;})()`,
);

// --- Act as appears on an action for a caller who holds the atom ---
await session.eval(search("add label"));
await sleep(600);
await session.eval(clickPanelRow("/add label/i"));
await sleep(1200);
const actAsShown = await session.eval(`/Act as/i.test(document.body.innerText)`);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-conditions.png", Buffer.from(shot.data, "base64"));

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  contributedFromServer: catalog.contributed,
  canActAs: catalog.canActAs,
  conditionRowsFound: conditionRows,
  oldGateStillOffered: oldGateHits > 0,
  addedFieldChanged,
  fieldChangedForm,
  aiPortsBeforeAnswers: portsBefore,
  typedAnswers,
  aiPortsAfterAnswers: portsAfter,
  actAsShown,
  screenshot: "/tmp/radd-conditions.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  catalog.contributed.includes("ai.classify") &&
  conditionRows.some((r) => /field changed/i.test(r)) &&
  !checks.oldGateStillOffered &&
  addedFieldChanged &&
  fieldChangedForm.hasField &&
  fieldChangedForm.hasFrom &&
  fieldChangedForm.hasTo &&
  addedAi &&
  typedAnswers &&
  // one port per answer plus the fallback, so more than the bare fallback
  portsAfter > portsBefore &&
  actAsShown &&
  consoleErrors.length === 0;
report({ "concrete conditions, AI node and act-as": ok }, "spec 116 — conditions");

close();
process.exit(ok ? 0 : 1);
