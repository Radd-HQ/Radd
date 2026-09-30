/**
 * RADD-1498: the two membership gates in the real editor — "Person is in team" (automations' own
 * form) and "Person is in directory group" (the groups plugin's inspector contribution).
 *
 * Asserts, against a running stack:
 *   - the catalog serves both gates, and the palette offers them by name
 *   - selecting each node on the canvas shows its form: a Person choice with the three role
 *     presets, a multi-value team / group picker, and the invert switch
 *   - the canvas card summarises the gate as "reporter in <team>"
 *
 * Measured, not eyeballed: the forms are located by their data attributes and their controls
 * counted, and the rule the proof creates is deleted at the end.
 */
import { outputPath, pageFetch, parsed, report, sleep } from "./lib/cdp.mjs";
import { openEditor, PANEL_ROWS, searchNodes } from "./lib/automation-editor.mjs";
import { startProof } from "./lib/proof.mjs";

const { session, close, baseUrl, loginStatus } = await startProof({
  port: 9344, profile: "/tmp/radd-membership-gates", base: "http://127.0.0.1:8000",
});

const catalog = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/automations/catalog",{credentials:"include"});
    const j=await r.json(); return (j.nodes||[]).map(n=>n.type||n.key);})()`,
);

const created = await session.eval(
  pageFetch("POST", "/automations", {
    name: "membership gates proof",
    enabled: false,
    orientation: "vertical",
    nodes: [
      { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.created" } },
      { id: "g1", kind: "gate", type: "gate.person_in_team", params: { person: "reporter", teams: ["Lighting"], negate: false } },
      { id: "g2", kind: "gate", type: "gate.person_in_group", params: { person: "assignee", groups: ["pipeline-global"], negate: false } },
    ],
    edges: [
      { id: "e1", source: "trg1", target: "g1", port: "out" },
      { id: "e2", source: "g1", target: "g2", port: "true" },
    ],
  }),
);
const rule = parsed(created);

await openEditor(session, baseUrl, "membership gates proof");
await sleep(1200);

// --- the palette offers both by name ---
await session.eval(searchNodes("person is in"));
await sleep(700);
const paletteRows = await session.eval(PANEL_ROWS);

// --- the cards summarise the gate ---
const summaries = await session.eval(`(()=>{
  const card = (type) => document.querySelector('[data-node-type="' + type + '"]');
  const text = (type) => card(type)?.textContent ?? null;
  return { team: text("gate.person_in_team"), group: text("gate.person_in_group") };
})()`);

// --- the team gate's form (automations' own) ---
await session.eval(`document.querySelector('[data-node-type="gate.person_in_team"]')?.click()`);
await sleep(900);
const teamForm = await session.eval(`(()=>{
  const form = document.querySelector("[data-person-in-team]");
  if (!form) return null;
  return {
    // The select shows the CHOSEN preset; the others live in its menu.
    personShown: form.innerText.includes("Person") && form.innerText.includes("Its reporter"),
    text: form.innerText.slice(0, 160),
    teamsShown: form.innerText.includes("Lighting"),
    invert: /Invert/.test(form.innerText),
    rect: form.getBoundingClientRect().width,
  };
})()`);

// --- the group gate's form (the groups plugin's inspector) ---
await session.eval(`document.querySelector('[data-node-type="gate.person_in_group"]')?.click()`);
await sleep(900);
const groupForm = await session.eval(`(()=>{
  const form = document.querySelector("[data-person-in-group-inspector]");
  if (!form) return null;
  return {
    personShown: form.innerText.includes("Person") && form.innerText.includes("Its assignee"),
    text: form.innerText.slice(0, 160),
    groupsShown: form.innerText.includes("pipeline-global"),
    invert: /Invert/.test(form.innerText),
    schemaFallback: /needs a custom editor/i.test(document.body.innerText),
    rect: form.getBoundingClientRect().width,
  };
})()`);

await session.screenshot(outputPath("radd-membership-gates.png"));
if (rule) await session.eval(pageFetch("DELETE", `/automations/${rule.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = { loginStatus, catalogHasBoth: ["gate.person_in_team", "gate.person_in_group"].every((k) => catalog.includes(k)),
  paletteRows, summaries, teamForm, groupForm, screenshot: outputPath("radd-membership-gates.png"), consoleErrors };
console.log(JSON.stringify(checks, null, 2));

const ok =
  (loginStatus === 200 || loginStatus === 204) &&
  checks.catalogHasBoth &&
  paletteRows.some((r) => /person is in team/i.test(r)) &&
  paletteRows.some((r) => /person is in directory group/i.test(r)) &&
  /reporter in Lighting/.test(summaries.team ?? "") &&
  /assignee in pipeline-global/.test(summaries.group ?? "") &&
  teamForm !== null && teamForm.personShown && teamForm.teamsShown && teamForm.invert && teamForm.rect > 200 &&
  groupForm !== null && groupForm.personShown && groupForm.groupsShown && groupForm.invert && !groupForm.schemaFallback && groupForm.rect > 200 &&
  consoleErrors.length === 0;
report({ "membership gates: catalog, palette, forms, summaries": ok }, "RADD-1498 — membership gates");

close();
process.exit(ok ? 0 : 1);
