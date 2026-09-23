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
  } finally {
    if (world?.projectId) await api(`return (await call("DELETE", "/projects/${world.projectId}")).status;`).catch(() => null);
    await close();
  }
  process.exit(report(checks) ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
