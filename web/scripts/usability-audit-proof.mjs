/**
 * RADD-1284 (usability audit) against a running Radd: each child issue's
 * observable claim, checked in a real browser on a throwaway project.
 *
 *   node scripts/usability-audit-proof.mjs [baseUrl] [email] [password]
 *
 * Sections are named by issue so a failure says which promise broke.
 */
import { mkdir } from "node:fs/promises";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const baseUrl = process.argv[2] || process.env.RADD_PROOF_BASE_URL || "http://127.0.0.1:8000";
const email = process.argv[3] || process.env.RADD_PROOF_EMAIL || "admin@example.com";
const password = process.argv[4] || process.env.RADD_PROOF_PASSWORD || "change-me";
const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-usability-audit-proof";

export async function waitFor(session, expression, tries = 40) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(250);
  }
  return false;
}

const text = (session) => session.eval(`(document.querySelector("main") || document.body).innerText`);

async function main() {
  await mkdir(output, { recursive: true });
  const { session, close } = await openBrowser({ port: 9539, profile: output + "/chrome", width: 1440, height: 1000 });
  const checks = {};
  const api = (body) => session.eval(`(async () => {
    const call = async (method, path, data) => {
      const r = await fetch("/api/v1" + path, { method, credentials: "include",
        headers: {"Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data) });
      const raw = await r.text();
      return { status: r.status, body: raw ? JSON.parse(raw) : null };
    };
    ${body}
  })()`);
  let world = null;
  try {
    await session.navigate(baseUrl + "/login", 1200);
    checks.loggedIn = (await session.login(baseUrl, email, password)) === 204;
    world = await api(`
      const key = "UA" + Math.random().toString(36).slice(2, 6).toUpperCase();
      const project = (await call("POST", "/projects", { key, name: "Usability audit proof" })).body;
      return { key, projectId: project.id };`);

    // --- RADD-1286: states are picked, never typed ---------------------------
    await session.navigate(`${baseUrl}/p/${world.key}/settings/sla`, 2500);
    checks["1286 SLA form has no typed state list"] = !(await text(session)).includes("comma-separated");
    checks["1286 SLA pause states is a picker"] = await waitFor(session,
      `!!document.querySelector('[aria-label="Pause the clock in these states"]')`);
    await session.navigate(`${baseUrl}/p/${world.key}/settings/workflow`, 2500);
    const workflow = await text(session);
    checks["1286 categories say they are shared"] = workflow.includes("Shared by every project");
    checks["1286 enforcement says whose value it is"] = workflow.includes("Same as the instance default")
      || workflow.includes("This project only");
    checks["1286 workflow names what happens on done"] = workflow.includes("When work is done");

    // --- RADD-1287: one vocabulary ------------------------------------------
    const item = await api(`return (await call("POST", "/items", { project_id: "${world.projectId}", title: "Vocabulary" })).body;`);
    await session.navigate(`${baseUrl}/issues/${item.key}`, 3000);
    const chrome = await session.eval(`document.body.innerText`);
    checks["1287 top bar says New issue"] = await session.eval(
      `[...document.querySelectorAll("button, a")].some(b => b.textContent.trim() === "New issue")`);
    checks["1287 no 'New item' anywhere"] = !chrome.includes("New item");
    checks["1287 sidebar says Portal"] = await session.eval(
      `[...document.querySelectorAll("aside a")].some(a => a.textContent.trim() === "Portal")`);
    checks["1287 visibility says who, not 'Normal'"] = (await session.eval(
      `[...document.querySelectorAll("label")].find(l => l.textContent.trim() === "Visibility")?.parentElement?.innerText ?? ""`))
      .includes("Project members");
    await session.navigate(`${baseUrl}/settings/instance`, 2000);
    checks["1287 server page has one name"] = await session.eval(
      `[...document.querySelectorAll("h1, h2")].some(h => h.textContent.trim() === "Server status")
        && [...document.querySelectorAll("a")].some(a => a.textContent.trim() === "Server status")
        && ![...document.querySelectorAll("a")].some(a => a.textContent.trim() === "Overview")`);

    // --- RADD-1289: copy for people -----------------------------------------
    const leak = /\b(?:[Ss]pecs? \d+|RADD-\d+)\b/;
    for (const path of [`/p/${world.key}/settings/general`, `/p/${world.key}/settings/sla`, "/settings/general",
      "/settings/directory", "/settings/ai", "/settings/email", "/settings/plugins"]) {
      await session.navigate(baseUrl + path, 2500);
      const copy = await text(session);  // a blank page would pass vacuously — require real content
      checks[`1289 no spec/ticket numbers on ${path.replace(world.key, "KEY")}`] = copy.length > 300 && !leak.test(copy);
    }
    await session.navigate(`${baseUrl}/settings/directory`, 2000);
    checks["1289 directory no longer says secrets live in env"] = !(await text(session)).includes("stay in environment variables");
    await session.navigate(`${baseUrl}/settings/automations`, 2000);
    checks["1289 automations no longer describe SLQ conditions"] = !(await text(session)).includes("SLQ condition");
    for (const path of ["workflow", "screens", "types", "sla"]) {
      await session.navigate(`${baseUrl}/p/${world.key}/settings/${path}`, 2000);
      checks[`1289 ${path} has no banner repeating the subtitle`] = (await text(session)).length > 300 && !(await session.eval(
        `!!document.querySelector('main [role="note"], main button[aria-label="Dismiss"]')`));
    }

    // --- RADD-1288: settings that behave -------------------------------------
    await session.navigate(`${baseUrl}/settings/general`, 2500);
    checks["1288 instance General has no Save buttons"] = (await text(session)).length > 300 && !(await session.eval(
      `[...document.querySelectorAll("main button")].some(b => b.textContent.trim() === "Save")`));
    await session.navigate(`${baseUrl}/p/${world.key}/settings/timelogging`, 2500);
    checks["1288 working week is seven day toggles"] = await waitFor(session,
      `document.querySelectorAll('[data-setting="work_week_days"] [data-day]').length === 7`);
    await session.click('[data-setting="work_week_days"] [data-day="sat"]');
    checks["1288 a day toggle saves itself"] = await waitFor(session,
      `(async () => (await (await fetch("/api/v1/scoped-settings?scope=project&scope_id=${world.projectId}", {credentials:"include"})).json()).find(r => r.key === "work_week_days")?.value === "mon,tue,wed,thu,fri,sat")()`);
    checks["1288 the row says Saved"] = await waitFor(session,
      `document.querySelector('[data-setting="work_week_days"] [data-save-state]')?.textContent.includes("Saved")`, 20);
    await waitFor(session, `!!document.querySelector('[data-setting="work_week_days"] button[title^="Reset"]')`);
    await session.click('[data-setting="work_week_days"] button[title^="Reset"]');
    checks["1288 Reset returns to inherited"] = await waitFor(session,
      `(async () => (await (await fetch("/api/v1/scoped-settings?scope=project&scope_id=${world.projectId}", {credentials:"include"})).json()).find(r => r.key === "work_week_days")?.set_here === false)()`);
    await session.navigate(`${baseUrl}/p/${world.key}/settings/sla`, 2500);
    const typeInto = async (selector, value) => {
      await session.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.focus(); el.select(); return true; })()`);
      await session.send("Input.insertText", { text: value });
      await sleep(300);
    };
    await typeInto('input[data-duration="resolution"]', "2h 30m");
    checks["1288 SLA durations take units"] = await waitFor(session,
      `document.body.innerText.includes("= 150m") || document.body.innerText.includes("= 2h 30m")`, 12);
    await typeInto('input[data-duration="resolution"]', "soon");
    checks["1288 a nonsense duration is refused"] = await waitFor(session,
      `document.body.innerText.includes("Use minutes or units")`, 12);
    await session.navigate(`${baseUrl}/settings/automations`, 2500);
    checks["1288 automations toggle is a switch"] = await session.eval(
      `!document.querySelector('main input[type="checkbox"]') && document.querySelectorAll('main [role="switch"]').length > 0`);
    await session.navigate(`${baseUrl}/settings/plugins`, 2500);
    checks["1288 plugin upload uses a kit button"] = await session.eval(
      `!!document.querySelector("[data-choose-wheel]") && document.querySelector('input[type="file"]')?.classList.contains("sr-only")`);

    // --- RADD-1290: releases and reports are project pages -------------------
    await api(`await call("POST", "/releases", { project_id: "${world.projectId}", name: "One", version: "1.0.0" });
      const issue = (await call("POST", "/items", { project_id: "${world.projectId}", title: "In the release" })).body;
      const rel = (await call("GET", "/releases?project_id=${world.projectId}")).body[0];
      await call("PATCH", "/items/" + issue.id, { release_id: rel.id }); return true;`);
    const views = await api(`return (await call("GET", "/views?project_id=${world.projectId}")).body;`);
    await session.navigate(`${baseUrl}/p/${world.key}/v/${views[0].id}`, 3000);
    checks["1290 a view links Reports"] = await waitFor(session, `!!document.querySelector('[data-view-link="reports"]')`);
    checks["1290 a view links Releases"] = await session.eval(`!!document.querySelector('[data-view-link="releases"]')`);
    await session.click('[data-view-link="releases"]');
    checks["1290 releases is a project page"] = await waitFor(session,
      `location.pathname === "/p/${world.key}/releases" && document.body.innerText.includes("· Releases")`);
    await waitFor(session, `!!document.querySelector('[data-release="1.0.0"] button[aria-expanded]')`);
    await session.click('[data-release="1.0.0"] button[aria-expanded]');
    checks["1290 a release lists its issues"] = await waitFor(session,
      `document.querySelector('[data-release-issues="1.0.0"]')?.textContent.includes("In the release")`);
    await session.navigate(`${baseUrl}/p/${world.key}/settings/releases`, 2500);
    checks["1290 the old settings address forwards"] = await waitFor(session, `location.pathname === "/p/${world.key}/releases"`);
    await session.navigate(`${baseUrl}/issues/${item.key}`, 3000);
    const header = await session.eval(`(() => {
      const labels = [...document.querySelectorAll("header button")].map(b => b.textContent.trim());
      return { archiveButton: labels.includes("Archive"), cloneButton: labels.includes("Clone"), deleteButton: labels.includes("Delete"),
               menu: !!document.querySelector('header [aria-label="Issue actions"]') };
    })()`);
    checks["1290 issue header keeps destructive actions behind a menu"] =
      header.menu && !header.archiveButton && !header.cloneButton && !header.deleteButton;
  } finally {
    if (world?.projectId) await api(`return (await call("DELETE", "/projects/${world.projectId}")).status;`).catch(() => null);
    await close();
  }
  process.exit(report(checks) ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
