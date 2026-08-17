
/**
 * RADD-941: the assignee picker actually offers people.
 *
 * 0.25.0 shipped it empty. `SelectField` builds its list by walking its own
 * children for `<option>`/`<optgroup>` (arrays and Fragments included), and
 * RADD-938 passed a COMPONENT element — which is none of those, so the walk
 * dropped it. No error, no warning, a one-entry dropdown.
 *
 * Every check that release ran was upstream of the render: the API returned the
 * right `has_access` values, tsc compiled, the bundle built. This asserts the
 * thing that was actually broken — how many options the control offers when a
 * person opens it.
 *
 * Note the two DOM facts that make this fiddly, both of which produced a
 * false "page didn't load" on the way here: Assignee and Reporter live behind
 * the collapsed MORE FIELDS section, and the control is a button rather than a
 * labelled combobox, so it is reached from its label's ancestors.
 */
import { openBrowser, report, sleep } from "./lib/cdp.mjs";
const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";
const { session, close } = await openBrowser({ port: 9387, profile: "/tmp/radd-people-picker", width: 1500, height: 1250, scale: 1 });
await session.navigate(baseUrl, 1500);
await session.login(baseUrl, email, password);
const key = await session.eval(
  `(async()=>{const r=await fetch("/api/v1/items?limit=1",{credentials:"include"});
     const j=await r.json(); return (j.items||j)[0].key;})()`);
await session.navigate(`${baseUrl}/issues/${key}`, 5000);
await session.eval(`(()=>{const b=[...document.querySelectorAll("button")].find(x=>/MORE FIELDS/i.test(x.textContent)); if(b) b.click();})()`);
await sleep(1800);

const openAssignee = await session.eval(
  `(()=>{const lab=[...document.querySelectorAll("*")].find(e=>e.childElementCount===0 && e.textContent.trim()==="Assignee");
     if(!lab) return "no label";
     let n=lab.parentElement, ctl=null;
     for(let i=0;i<4 && n && !ctl;i++){ ctl=n.querySelector("[role=combobox],select,button[aria-haspopup]"); n=n.parentElement; }
     if(!ctl) return "no control";
     ctl.click(); return "opened:"+ctl.tagName;})()`);
await sleep(1300);
const opts = await session.eval(
  `(()=>{const rows=[...document.querySelectorAll("[role=option]")];
     return {count: rows.length, sample: rows.slice(0,6).map(r=>r.textContent.trim()),
             headers: rows.filter(r=>r.getAttribute("aria-disabled")==="true").map(r=>r.textContent.trim())};})()`);

const failed = report({
  "assignee control opened": String(openAssignee).startsWith("opened"),
  "the dropdown offers people (the 0.25.0 regression)": opts.count > 1,
  "no console errors": session.consoleErrors.length === 0,
}, { openAssignee, opts, errors: session.consoleErrors.slice(0,3) });
close();
process.exit(failed ? 1 : 0);
