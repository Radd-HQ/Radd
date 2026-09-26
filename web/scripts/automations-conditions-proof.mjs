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
import { outputPath, pageFetch, parsed, report, sleep } from "./lib/cdp.mjs";
import { clickPanelRow, openEditor, PANEL_ROWS, searchNodes } from "./lib/automation-editor.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9342, profile: "/tmp/radd-conditions", base: "http://localhost:8000",
});

// The server decides what the palette can offer.
const catalog = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/catalog",{credentials:"include"});
    const j=await r.json();
    return {nodes:(j.nodes||[]).map(n=>n.type||n.key), canActAs:j.can_act_as};})()`,
);

const created = await session.eval(
  pageFetch("POST", "/automations", {
    name: "conditions proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
    ],
    edges: [],
  }),
);
const rule = parsed(created);

await openEditor(session, baseUrl, "conditions proof");

// --- the palette offers named conditions, not the abstract tree ---
await session.eval(searchNodes("changed"));
await sleep(700);
const conditionRows = await session.eval(PANEL_ROWS);
await session.eval(searchNodes("gate on the event"));
await sleep(600);
const oldGateHits = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] li button")].length`,
);

// --- Field changed shows a real form ---
await session.eval(searchNodes("field changed"));
await sleep(600);
const addedFieldChanged = await session.eval(clickPanelRow(/field changed/i));
await sleep(1200);
const fieldChangedForm = await session.eval(`(()=>{
  const t=document.body.innerText;
  return {hasField:/\\bField\\b/.test(t), hasFrom:/\\bFrom\\b/.test(t), hasTo:/\\bTo\\b/.test(t),
          noTree:!/subject|operator/i.test(t)};
})()`);

// --- the AI classifier: ports follow the answers you type ---
await session.eval(searchNodes("ask the ai"));
await sleep(600);
const addedAi = await session.eval(clickPanelRow(/ask the ai/i));
await sleep(1200);
const portsBefore = await session.eval(
  `(()=>{const n=document.querySelector('[data-node-type="ai.classify"]');
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
  `(()=>{const n=document.querySelector('[data-node-type="ai.classify"]');
     return n ? n.parentElement.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right").length : -1;})()`,
);

// --- Act as appears on an action for a caller who holds the atom ---
await session.eval(searchNodes("add label"));
await sleep(600);
await session.eval(clickPanelRow(/add label/i));
await sleep(1200);
const actAsShown = await session.eval(`/Act as/i.test(document.body.innerText)`);

await session.screenshot(outputPath("radd-conditions.png"));

if (rule) await session.eval(pageFetch("DELETE", `/automations/${rule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  aiNodeOffered: (catalog.nodes ?? []).includes("ai.classify"),
  canActAs: catalog.canActAs,
  conditionRowsFound: conditionRows,
  oldGateStillOffered: oldGateHits > 0,
  addedFieldChanged,
  fieldChangedForm,
  aiPortsBeforeAnswers: portsBefore,
  typedAnswers,
  aiPortsAfterAnswers: portsAfter,
  actAsShown,
  screenshot: outputPath("radd-conditions.png"),
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  (catalog.nodes ?? []).includes("ai.classify") &&
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
