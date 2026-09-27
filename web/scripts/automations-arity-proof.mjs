/**
 * RADD-918/919: node arity (once / per item) and the SLQ search node.
 *
 * Asserts, in the real UI:
 *   - the server serves `node_arity` for BUILT-IN types, not just contributed
 *     ones — the editor's default has to come from the engine or it can silently
 *     disagree with it
 *   - the palette offers "Find issues (SLQ)", the only node that PRODUCES items,
 *     and selecting it shows its own form
 *   - `create_item` draws TWO output handles (out + created), so what it made is
 *     wireable
 *   - the Run control appears on an action that can read either way and is
 *     ABSENT on one that cannot — a segmented control with one setting teaches
 *     nothing
 *   - choosing per item writes the param AND changes the card badge
 *   - choosing a ROLE recipient on send_email locks the control to per item,
 *     because "the reporter" is a property of one issue
 *
 * Measured, not eyeballed: presence in the DOM is not visibility, and a control
 * that renders is not one that is wired.
 */
import { outputPath, pageFetch, parsed, report, sleep } from "./lib/cdp.mjs";
import { clickPanelRow, openEditor, PANEL_ROWS, searchNodes } from "./lib/automation-editor.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9347, profile: "/tmp/radd-arity", base: "http://localhost:8000",
});

/** The Run control's state: which options exist, which is checked, which are locked. */
const readArity = `(()=>{
  const group=document.querySelector('[role="radiogroup"][aria-label="Run"]');
  if(!group) return null;
  return [...group.querySelectorAll('[role="radio"]')].map(b=>({
    label:(b.querySelector("span")||b).textContent.trim(),
    checked:b.getAttribute("aria-checked")==="true",
    disabled:b.disabled,
  }));})()`;

/** Handles on the node currently matching a type, for the port count. */
const handlesOf = (type) => `(()=>{
  const n=document.querySelector('[data-node-type="${type}"]');
  if(!n) return -1;
  return n.parentElement.querySelectorAll(".react-flow__handle-bottom, .react-flow__handle-right").length;})()`;

// The SERVER is the source of truth for how each node type reads its packet.
const catalog = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/catalog",{credentials:"include"});
    const j=await r.json();
    const by=Object.fromEntries((j.node_arity||[]).map(a=>[a.type,a]));
    return {
      createItem: by["action.create_item"],
      setState: by["action.set_state"],
      filter: by["filter.slq"],
      search: by["search.slq"],
      aiClassify: by["ai.classify"],
      tokens: (j.tokens||[]).map(t=>t.token),
    };})()`,
);

const created = await session.eval(
  pageFetch("POST", "/automations", {
    name: "arity proof",
    enabled: false,
    orientation: "vertical",
    nodes: [{ id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } }],
    edges: [],
  }),
);
const rule = parsed(created);

await openEditor(session, baseUrl, "arity proof");

// --- the search node is offered, and has its own form ---
await session.eval(searchNodes("find issues"));
await sleep(700);
const searchRows = await session.eval(PANEL_ROWS);
const addedSearch = await session.eval(clickPanelRow(/find issues/i));
await sleep(1200);
const searchForm = await session.eval(`(()=>{
  const t=document.body.innerText;
  return {hasQuery:/Find issues where/i.test(t), hasScope:/Within/i.test(t),
          hasMode:/What reaches this node/i.test(t)};})()`);
// A source has no Run control: it produces the set rather than reading one.
const searchArity = await session.eval(readArity);

// --- create_item draws BOTH of its outputs ---
await session.eval(searchNodes("create issue"));
await sleep(600);
const addedCreate = await session.eval(clickPanelRow(/create issue/i));
await sleep(1400);
const createPorts = await session.eval(handlesOf("action.create_item"));
const createArity = await session.eval(readArity);
const badgeBefore = await session.eval(
  `(()=>{const n=document.querySelector('[data-node-type="action.create_item"]');
   return n ? (n.querySelector("[data-node-arity]")||{}).textContent ?? null : null;})()`,
);

// --- switching it to per item writes the param and moves the badge ---
const switched = await session.eval(`(()=>{
  const group=document.querySelector('[role="radiogroup"][aria-label="Run"]');
  const perItem=[...group.querySelectorAll('[role="radio"]')].find(b=>/per issue/i.test(b.textContent));
  if(!perItem) return false; perItem.click(); return true;})()`);
await sleep(1200);
const badgeAfter = await session.eval(
  `(()=>{const n=document.querySelector('[data-node-type="action.create_item"]');
   return n ? (n.querySelector("[data-node-arity]")||{}).textContent ?? null : null;})()`,
);

// --- an action with only one coherent reading shows no control at all ---
await session.eval(searchNodes("add label"));
await sleep(600);
await session.eval(clickPanelRow(/add label/i));
await sleep(1200);
const labelArity = await session.eval(readArity);

// --- a role recipient locks send_email to per item, and an address frees it ---
// Its blank params name the `reporter` ROLE, so a freshly dropped node must
// already be per item: it is the only mode in which that recipient resolves,
// and the server refuses to store the other pairing.
await session.eval(searchNodes("send email"));
await sleep(600);
await session.eval(clickPanelRow(/send email/i));
await sleep(1300);
const emailArityWithRole = await session.eval(readArity);

// A role recipient is per-issue only. Since RADD-1425 the send_email inspector is mailintake's:
// choosing "Once for all issues" snaps back to per issue instead of the option being greyed out.
await session.eval(`(()=>{const group=document.querySelector('[role="radiogroup"][aria-label="Run"]');
  const once=group && [...group.querySelectorAll('[role="radio"]')].find(b=>/all issues/i.test(b.textContent));
  if(once) once.click(); return Boolean(once);})()`);
await sleep(1200);
const emailArityAfterOnce = await session.eval(readArity);

// The recipient is a datalist-backed free-text field, so it is addressed by its
// placeholder — the label is a sibling, not an ancestor.
const typedAddress = await session.eval(`(()=>{
  const input=[...document.querySelectorAll("input")]
    .find(i=>/reporter . assignee/i.test(i.placeholder||""));
  if(!input) return false;
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,"value").set;
  setter.call(input,"ops@example.com");
  input.dispatchEvent(new Event("input",{bubbles:true}));
  return true;})()`);
await sleep(1300);
const emailArityWithAddress = await session.eval(readArity);

await session.screenshot(outputPath("radd-arity.png"));

if (rule) await session.eval(pageFetch("DELETE", `/automations/${rule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checked = (state) => (state ?? []).find((option) => option.checked)?.label ?? null;

const checks = {
  loginStatus,
  servedArity: catalog,
  searchRowsFound: searchRows,
  addedSearch,
  searchForm,
  searchHasNoRunControl: searchArity === null,
  addedCreate,
  createItemPorts: createPorts,
  createItemRunOptions: (createArity ?? []).map((o) => o.label),
  badgeBefore,
  switched,
  badgeAfter,
  addLabelHasNoRunControl: labelArity === null,
  emailWithRole: checked(emailArityWithRole),
  emailOnceSnapsBack: /per issue/i.test(checked(emailArityAfterOnce) ?? ""),
  typedAddress,
  emailWithAddress: checked(emailArityWithAddress),
  emailUnlockedByAddress: (emailArityWithAddress ?? []).every((o) => !o.disabled),
  screenshot: outputPath("radd-arity.png"),
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  // built-in types carry arity, and the fixed/configurable split is the server's
  catalog.createItem?.options?.length === 2 &&
  catalog.setState?.options?.length === 1 &&
  catalog.setState?.default === "item" &&
  catalog.search?.default === "set" &&
  catalog.aiClassify?.options?.length === 2 &&
  catalog.tokens.includes("{{items.keys}}") &&
  addedSearch &&
  searchForm.hasQuery &&
  searchForm.hasScope &&
  searchForm.hasMode &&
  checks.searchHasNoRunControl &&
  addedCreate &&
  createPorts === 2 && // out + created
  checks.createItemRunOptions.length === 2 &&
  badgeBefore?.trim() === "once" &&
  switched &&
  badgeAfter?.trim() === "per issue" &&
  checks.addLabelHasNoRunControl &&
  checks.emailWithRole === "Once per issue" &&
  checks.emailOnceSnapsBack &&
  typedAddress &&
  checks.emailUnlockedByAddress &&
  consoleErrors.length === 0;

report({ "arity control, search node and the created port": ok }, "RADD-918/919 — arity");

close();
process.exit(ok ? 0 : 1);
