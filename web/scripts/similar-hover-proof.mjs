/**
 * RADD-906 + RADD-924: the mod-key label, and the similar-issues hover preview.
 *
 * Two things a screenshot cannot settle, so both are measured:
 *
 *   - **The modifier label.** Headless Chrome here is Linux, so every shortcut
 *     hint must read `Ctrl+K`, not `⌘K`. The failure this fixes was silent:
 *     the handlers always accepted both, so the shortcut WORKED and the label
 *     told a Linux user to press a key their keyboard does not have.
 *   - **The hover preview.** The FLATTENER is unit-tested in
 *     `plain-text.test.mjs` — proving it here meant hovering whatever the
 *     similar-issues ranker happened to return, and on a 500k-item database
 *     that was an issue with no description at all, so the assertion passed by
 *     describing nothing. This proves the WIRING: dwell, position, content,
 *     dismissal.
 *
 *     `(hover: none)` is the headless BASELINE, and
 *     Tailwind gates every `hover:` utility on `@media (hover: hover)` — so a
 *     proof that does not set `primaryHoverType` reports un-hovered styles for
 *     a correctly-hovered element. `lib/chrome.mjs` carries the flag; this
 *     asserts it took, then drives a REAL pointer through CDP rather than a
 *     synthetic MouseEvent, because the dwell timer is on mouseenter.
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "hussein@hjarrar.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9361, profile: "/tmp/radd-hover" });

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// The flag that makes hover assertions mean anything at all.
const hoverIsReal = await session.eval(`matchMedia("(hover: hover)").matches`);

// --- RADD-906: the shortcut hint names a key this keyboard has ---------------
await session.navigate(`${baseUrl}/my-work`, 2500);
const modLabels = await session.eval(`(()=>{
  const text = document.body.innerText;
  const titles = [...document.querySelectorAll('[title]')].map(n=>n.getAttribute('title'));
  return {
    bodyHasCommandGlyph: text.includes("\\u2318"),
    bodyHasCtrl: /Ctrl\\+K/.test(text),
    titlesWithGlyph: titles.filter(t=>t && t.includes("\\u2318")),
    searchHint: (titles.find(t=>t && /Search —/.test(t)) || ""),
  };})()`);

// --- RADD-924: the hover preview on a similar-issues candidate ----------------
// Two near-identical issues are SEEDED, one carrying a markdown description, so
// the flattener is genuinely exercised. Hovering whatever the dev database
// happened to return proved nothing: the first run found a candidate with no
// description at all, which made the "no raw markdown" assertion vacuously
// true — the exact failure mode a proof exists to avoid.
// Sweep anything a previous run leaked BEFORE seeding. A proof that creates
// data must not accumulate it: an earlier failure exited before its cleanup,
// and the next run then hovered the orphan instead of its own fixture.
await session.eval(`(async()=>{
  const r=await fetch("/api/v1/items?q="+encodeURIComponent('title ~ "hovercard proof"')+"&limit=50",
    {credentials:"include"});
  if(!r.ok) return 0;
  const j=await r.json();
  const items=j.items||j;
  for (const item of items) {
    await fetch("/api/v1/items/"+item.id,{method:"DELETE",credentials:"include"});
  }
  return items.length;})()`);

const stamp = Math.random().toString(36).slice(2, 8);
const seedTitle = `hovercard proof ${stamp} render farm outage`;
const MARKDOWN = [
  "## What happened",
  "",
  "The `render farm` went down mid-sync. See [the runbook](https://example.com/runbook).",
  "",
  "- nodes stopped responding",
  "- the queue backed up",
].join("\n");

const seeded = await session.eval(
  `(async()=>{
    const projects=await (await fetch("/api/v1/projects",{credentials:"include"})).json();
    const project=projects[0];
    const make=async(title,description)=>{
      const r=await fetch("/api/v1/items",{method:"POST",credentials:"include",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({project_id:project.id,title,description})});
      return r.ok ? await r.json() : null;
    };
    const target=await make(${JSON.stringify(seedTitle + " duplicate")}, ${JSON.stringify(MARKDOWN)});
    const origin=await make(${JSON.stringify(seedTitle)}, "");
    return {origin, target};})()`,
);

// The search indexer is an outbox CONSUMER, so the seeds become findable only
// once it has caught up — which right after a server restart can take longer
// than any sleep worth writing. Poll for the twin instead of guessing: a fixed
// wait against an async consumer is the flake that costs an hour six months
// from now (this proof failed exactly once, first-in-batch, for this reason).
let indexed = false;
for (let attempt = 0; attempt < 12 && !indexed; attempt++) {
  await sleep(1000);
  indexed = await session.eval(
    `(async()=>{const r=await fetch("/api/v1/ai/similar",{method:"POST",credentials:"include",
       headers:{"Content-Type":"application/json"},
       body:JSON.stringify({text:${JSON.stringify(seedTitle)}, exclude_item_id:null})});
     if(!r.ok) return false;
     const j=await r.json();
     return (j.candidates||[]).some(c=>c.item_key===${JSON.stringify(seeded?.target?.key ?? "")});})()`,
  );
}

let hover = { reason: "seeding failed" };
if (seeded?.origin && seeded?.target) {
  await session.navigate(`${baseUrl}/issues/${seeded.origin.key}`, 3000);
  await session.eval(
    `(()=>{const b=[...document.querySelectorAll("button")].find(n=>/find similar/i.test(n.textContent));
      if(b) b.click(); return !!b;})()`,
  );
  await sleep(5000);

  // Whichever candidate came back first. Which one it is does not matter — the
  // ranker's opinion is not what is under test, and depending on it made this
  // proof flaky on a database with half a million issues.
  const row = await session.eval(`(()=>{
    const link=[...document.querySelectorAll("a")]
      .find(a=>/^[A-Z][A-Z0-9]*-\\d+/.test(a.innerText.trim()));
    if(!link) return null;
    const wanted=link.innerText.trim().match(/^[A-Z][A-Z0-9]*-\\d+/)[0];
    const li=link.closest("li");
    const r=li.getBoundingClientRect();
    return {key:wanted, x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)};})()`);

  if (row) {
    // A REAL pointer. A synthetic MouseEvent carries none of the hover state the
    // dwell and the CSS both depend on.
    await session.send("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: row.x, y: row.y, buttons: 0,
    });
    await sleep(1800); // past the 350ms dwell, plus the fetch

    hover = await session.eval(`(()=>{
      const card=document.querySelector("[data-similar-hover-card]");
      if(!card) return {opened:false};
      const r=card.getBoundingClientRect();
      const text=card.innerText.replace(/\\s+/g," ").trim();
      return {
        opened:true,
        forKey:card.getAttribute("data-similar-hover-card"),
        onScreen: r.top >= 0 && r.left >= 0 &&
                  r.bottom <= window.innerHeight && r.right <= window.innerWidth,
        width: Math.round(r.width),
        hasStateOrPriority: /todo|progress|done|review|triage|backlog|low|normal|high|blocker/i.test(text),
        // The seeded description reached the card...
        hasDescriptionProse: /render farm went down mid-sync/i.test(text),
        // ...flattened: the link keeps its TEXT and loses its URL, and the
        // bullets are readable. \\x60 for the fence — a literal backtick would
        // close the template this expression is written inside.
        keepsLinkText: /the runbook/i.test(text) && !/example\\.com/i.test(text),
        flattensBullets: /. nodes stopped responding/i.test(text),
        hasRawMarkdown: /\\x60|##|\\]\\(http/.test(text),
        text: text.slice(0, 240),
      };})()`);

    await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 5, y: 5, buttons: 0 });
    await sleep(500);
    hover.closesOnLeave = await session.eval(
      `document.querySelector("[data-similar-hover-card]") === null`,
    );
  } else {
    hover = { opened: false, reason: "the seeded twin did not come back as a candidate" };
  }
}

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-hover.png", Buffer.from(shot.data, "base64"));

// Awaited IN THE PAGE. A bare `fetch().then()` handed to eval resolves before
// the request lands, which is why every earlier run leaked its two fixtures and
// the next run then hovered an orphan instead of its own.
const teardown = await session.eval(`(async()=>{
  const ids = ${JSON.stringify([seeded?.origin?.id, seeded?.target?.id].filter(Boolean))};
  const codes = [];
  for (const id of ids) {
    const r = await fetch("/api/v1/items/" + id, {method:"DELETE", credentials:"include"});
    codes.push(r.status);
  }
  return codes;})()`);

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const checks = {
  loginStatus,
  hoverIsReal,
  modLabels,
  seededKeys: [seeded?.origin?.key, seeded?.target?.key],
  seedsWereIndexed: indexed,
  teardown,
  hover,
  screenshot: "/tmp/radd-hover.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  hoverIsReal && // otherwise every hover assertion below is meaningless
  // RADD-906: this is a Linux box — no ⌘ anywhere, and the hint names Ctrl.
  modLabels.bodyHasCommandGlyph === false &&
  modLabels.titlesWithGlyph.length === 0 &&
  modLabels.bodyHasCtrl &&
  // The rail's title only exists while the sidebar is COLLAPSED, so it is
  // asserted when present rather than required — a proof that demands an
  // element the layout may not render fails for the wrong reason.
  (!modLabels.searchHint || /Ctrl\+K/.test(modLabels.searchHint)) &&
  // RADD-924: the preview opens on dwell, stays on screen, says something, and
  // gets out of the way again.
  indexed &&
  hover.opened &&
  hover.onScreen &&
  hover.hasStateOrPriority &&
  hover.hasDescriptionProse &&
  hover.keepsLinkText &&
  hover.flattensBullets &&
  hover.hasRawMarkdown === false &&
  hover.closesOnLeave &&
  consoleErrors.length === 0;

report({ "mod-key labels and the similar-issue hover preview": ok }, "RADD-906 + RADD-924");

close();
process.exit(ok ? 0 : 1);
