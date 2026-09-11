/**
 * Render proof for the empty-instance shell (RADD-1132 / RADD-1133).
 *
 * A fresh install has ZERO projects, and two things that were invisible on
 * every instance the project had ever run on (all of which had projects since
 * before the gates existed) turned the first admin's session into a wall:
 *
 *  - **The sidebar hid the whole Projects section** when the instance had none,
 *    and that section is the only path to "New project" — the admin could not
 *    find where to create the first project.
 *  - **The member floor refused the timesheet** for an account holding
 *    `item.read` globally, because the per-project map is empty for everyone
 *    when there are no projects (the backend half, asserted here only as the
 *    absence of the permission toast).
 *
 * Run against an instance with NO projects — the point of the proof is the
 * empty state, and a database with a project passes the first check vacuously.
 * The script refuses to run when the directory is not empty.
 *
 * Usage:
 *   node scripts/empty-instance-proof.mjs <baseUrl> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9459;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-empty-instance-proof");

const SIDEBAR_PROBE = `(() => {
  const aside = document.querySelector("aside");
  const text = aside ? aside.textContent || "" : "";
  const buttons = [...document.querySelectorAll("aside button")];
  const newProject = buttons.find((b) => (b.textContent || "").trim() === "New project");
  const rect = newProject ? newProject.getBoundingClientRect() : null;
  return {
    hasAside: Boolean(aside),
    hasProjectsHeader: /Projects/.test(text),
    saysNoProjectsYet: /No projects yet/.test(text),
    newProjectVisible: Boolean(rect && rect.width > 0 && rect.height > 0),
    newProjectHeight: rect ? Math.round(rect.height) : 0,
  };
})()`;

const MODAL_PROBE = `(() => {
  const dialog = document.querySelector('[role="dialog"]');
  return {
    open: Boolean(dialog),
    title: dialog ? (dialog.querySelector("h2, h1, [id$=title]") || {}).textContent || "" : "",
    hasKeyInput: Boolean(dialog && dialog.querySelector("input")),
  };
})()`;

const TIMESHEET_PROBE = `(() => {
  const main = document.querySelector("main") || document.body;
  const text = main.textContent || "";
  return {
    permissionToast: /don't have access|permission 'item\\.read' denied/.test(text),
    hasGrid: /Group by/.test(text),
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // Precondition: the instance really is empty, or every check below is vacuous.
  const total = await session.eval(
    `fetch("/api/v1/projects").then(r => r.json()).then(d => Array.isArray(d) ? d.length : (d.total ?? -1))`,
  );
  if (total !== 0) {
    console.error(`refusing to run: the instance has ${total} project(s); this proof needs zero`);
    process.exit(2);
  }

  // --- RADD-1133: the Projects section survives an empty instance ---
  await session.navigate(baseUrl + "/", 2500);
  const sidebar = await session.eval(SIDEBAR_PROBE);
  checks["sidebar renders"] = sidebar.hasAside;
  checks["Projects section is present with zero projects"] = sidebar.hasProjectsHeader;
  checks["it says 'No projects yet.'"] = sidebar.saysNoProjectsYet;
  checks["'New project' is a visible, laid-out control"] = sidebar.newProjectVisible;

  // Guarded: on the old code there is no button, and a proof should say so on a
  // FAIL line rather than die inside the click helper.
  let modal = { open: false, title: "", hasKeyInput: false };
  if (sidebar.newProjectVisible) {
    await session.click("aside button", '(t) => t.trim() === "New project"');
    await sleep(600);
    modal = await session.eval(MODAL_PROBE);
  }
  checks["clicking it opens the New project dialog"] = modal.open && modal.hasKeyInput;

  // --- RADD-1132: the timesheet is an empty state, not a permission toast ---
  await session.navigate(baseUrl + "/timesheet", 2500);
  const timesheet = await session.eval(TIMESHEET_PROBE);
  checks["timesheet shows its grid controls"] = timesheet.hasGrid;
  checks["timesheet shows NO permission toast (backend on 0.36.3+)"] = !timesheet.permissionToast;

  process.exit(report(checks, { sidebar, modal, timesheet }) ? 1 : 0);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
