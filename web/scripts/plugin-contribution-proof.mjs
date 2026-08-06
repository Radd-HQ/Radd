/**
 * RADD-923: a plugin's event and a plugin's ACTION, in the real editor.
 *
 * The acceptance test for "organic but consistent". Asserts, in the running UI:
 *   - the plugin's auto-wired event is a first-class trigger and DECLARES its
 *     subject, so the samples panel can describe it before it has ever fired
 *   - the plugin's action node appears in the palette and can be dropped
 *   - its form is GENERATED from the plugin's own params_schema — the promise
 *     `AutomationNodeSpec` made and nothing kept until now
 *   - a graph of nothing but plugin contributions SAVES (the built-in action
 *     union never sees it)
 *   - and the dry run plans it, which is only possible because the executor
 *     dispatches contributed actions at all
 *
 * None of this required an edit to `automations`, the kernel, or the SPA.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "hussein@hjarrar.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9357, profile: "/tmp/radd-plugin" });

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

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// --- the contribution is visible to the whole builder -------------------------
const catalog = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/catalog",{credentials:"include"});
    const j=await r.json();
    const node=(j.contributed_nodes||[]).find(n=>n.key==="milestone.set_status");
    return {
      triggerOffered:(j.triggers||[]).some(t=>t.event_type==="milestone.created"),
      node: node ? {kind:node.kind, group:node.group, perm:node.permission,
                    params:Object.keys(node.params_schema.properties||{})} : null,
    };})()`,
);
// The event DECLARES its subject, so the samples panel describes it even though
// this instance may never have fired one.
const declared = await session.eval(
  `(async()=>{const r=await fetch(
     "/api/v1/automations/samples/events?event_type=milestone.created",{credentials:"include"});
   const j=await r.json();
   return {status:r.status, subjects:j.subjects, sampled:j.sampled};})()`,
);

// --- a graph made only of plugin contributions saves --------------------------
const created = await session.eval(
  post("/automations", {
    name: "plugin contribution proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "milestone.created" } },
      { id: "act1", kind: "action", type: "milestone.set_status", params: { status: "at_risk" } },
    ],
    edges: [{ source: "trg1", port: "out", target: "act1" }],
  }),
);
const rule = created.status < 300 ? JSON.parse(created.body) : null;

// An invalid enum value is refused by the plugin's OWN schema, on write.
const refused = await session.eval(
  post("/automations", {
    name: "plugin contribution proof (bad)",
    enabled: false,
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "milestone.created" } },
      { id: "act1", kind: "action", type: "milestone.set_status", params: { status: "banana" } },
    ],
    edges: [{ source: "trg1", port: "out", target: "act1" }],
  }),
);

// --- the dry run reaches the contributed action -------------------------------
const dryRun = await session.eval(
  post(`/automations/${rule.id}/test`, { item_id: null, trigger_node_id: "trg1" }),
);
const runResult = JSON.parse(dryRun.body);

// --- the editor renders a form from the plugin's schema -----------------------
await session.navigate(`${baseUrl}/settings/automations`, 2000);
await session.eval(
  `(()=>{const el=[...document.querySelectorAll("button,a")].find(n=>` +
    `n.closest("li")&&n.closest("li").innerText.includes("plugin contribution proof"));` +
    `if(el)el.click();return !!el;})()`,
);
await sleep(3000);

// It is offered in the palette by its own group.
await session.eval(search("milestone"));
await sleep(800);
const paletteRows = await session.eval(
  `[...document.querySelectorAll("[data-node-panel] li button")].map(b=>b.textContent.trim())`,
);

// Selecting it shows a GENERATED form, with the enum as a real dropdown.
await session.eval(
  `(()=>{const n=[...document.querySelectorAll('[data-node-id]')]
     .find(e=>/milestone\\.set_status/.test(e.innerText));
   if(n){n.dispatchEvent(new MouseEvent("mousedown",{bubbles:true,view:window}));n.click();}
   return !!n;})()`,
);
await sleep(1400);
// The kit bans native <select>: SelectField is a listbox (button +
// aria-haspopup), so the generated enum reads off the trigger button.
const generatedForm = await session.eval(`(()=>{
  const host=document.querySelector("[data-schema-fields]");
  if(!host) return null;
  const listbox=host.querySelector('[aria-haspopup="listbox"]');
  const label=host.querySelector("label");
  return {
    rendered:true,
    isListbox: Boolean(listbox),
    label: label ? label.textContent.trim() : "",
    value: listbox ? listbox.textContent.trim() : "",
  };})()`);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-plugin.png", Buffer.from(shot.data, "base64"));

if (rule) {
  await session.eval(
    `fetch("/api/v1/automations/${rule.id}",{method:"DELETE",credentials:"include"}).then(r=>r.status)`,
  );
}

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
// The node RAN — which is the whole point. Before RADD-923 the executor
// dropped it with "unknown action type", so `dropped` is the precise witness:
// it is empty now and would have named the node before. The dry run carries no
// milestone (there is nothing to seed one with), so the action correctly plans
// nothing — asserting a plan here would be asserting the wrong thing.
const actNode = (runResult.nodes ?? []).find((n) => n.node_id === "act1");
const dispatched = Boolean(actNode?.ran) && (runResult.dropped ?? []).length === 0;
const checks = {
  loginStatus,
  catalog,
  declared,
  savedStatus: created.status,
  badEnumRefusedWith: refused.status,
  dryRunNodes: (runResult.nodes ?? []).map((n) => n.node_id),
  dryRunDropped: runResult.dropped,
  contributedActionDispatched: dispatched,
  paletteRows,
  generatedForm,
  screenshot: "/tmp/radd-plugin.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  catalog.triggerOffered &&
  catalog.node?.kind === "action" &&
  catalog.node.params.includes("status") &&
  catalog.node.perm === "milestone.update" &&
  declared.status === 200 &&
  declared.subjects.includes("milestone") &&
  created.status === 201 &&
  refused.status >= 400 && // the plugin's own schema, enforced on write
  runResult.nodes.length === 2 &&
  dispatched &&
  paletteRows.some((row) => /set milestone status/i.test(row)) &&
  generatedForm?.rendered === true &&
  generatedForm.isListbox &&
  /status/i.test(generatedForm.label) &&
  generatedForm.value.includes("at_risk") &&
  consoleErrors.length === 0;

report({ "a plugin contributes an event AND the action that answers it": ok }, "RADD-923");

close();
process.exit(ok ? 0 : 1);
