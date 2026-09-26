/**
 * RADD-1285 against a running Radd: shipping is a workflow transition.
 *
 * On a fresh project with a Waiting → Done transition: tick "Moves automatically
 * when a release is published" in Workflow; "Requires a release" then shows on
 * and fixed; a person cannot move the waiting issue to Done without a release;
 * the Releases page names the move; publishing a release ships the issue with
 * the release recorded. The project is deleted at the end.
 *
 *   node scripts/release-transitions-proof.mjs [baseUrl] [email] [password]
 */
import { mkdir } from "node:fs/promises";
import { PAGE_API, report, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-release-transitions-proof";

async function main() {
  await mkdir(output, { recursive: true });
  const { session, close, baseUrl, loginStatus } = await startProof({
    port: 9538, profile: output + "/chrome", width: 1440, height: 1100,
  });
  const checks = { loggedIn: loginStatus === 204 };
  const inPage = (body) => session.eval(`(async () => { ${PAGE_API} ${body} })()`);
  let world = null;
  try {
    world = await inPage(`
      const key = "RT" + Math.random().toString(36).slice(2, 6).toUpperCase();
      const project = (await api("POST", "/projects", { key, name: "Release transitions proof" })).body;
      const waiting = (await api("POST", "/states", { project_id: project.id, name: "Waiting for release", category: "done" })).body;
      const states = (await api("GET", "/states?project_id=" + project.id)).body;
      const done = states.find(s => s.name === "Done");
      const transition = (await api("POST", "/transitions", { project_id: project.id, from_state_id: waiting.id, to_state_id: done.id })).body;
      await api("PUT", "/scoped-settings", { scope: "project", scope_id: project.id, key: "workflow_transition_mode", value: "guards" });
      const item = (await api("POST", "/items", { project_id: project.id, title: "Ship me" })).body;
      await api("PATCH", "/items/" + item.id, { state_id: waiting.id });
      return { key, projectId: project.id, waiting: waiting.id, done: done.id, transition: transition.id, item: item.id, itemKey: item.key };`);
    checks.seeded = Boolean(world?.transition && world.item);

    await session.navigate(`${baseUrl}/p/${world.key}/settings/workflow`, 2500);
    const box = `document.querySelector('[data-transition-on-release]')`;
    checks.switchOffedFirst = await waitFor(session, `!!${box} && !${box}.checked && !${box}.disabled`);
    await session.click("[data-transition-on-release]");
    checks.savedOnRelease = await waitFor(session, `(async () => (await (await fetch("/api/v1/projects/${world.projectId}/transitions", {credentials:"include"})).json()).find(t => t.id === "${world.transition}")?.on_release === true)()`);
    checks.requiresReleaseShownFixed = await waitFor(session,
      `(() => { const b = document.querySelector('[data-transition-requires-release]'); return !!b && b.checked && b.disabled; })()`);
    await session.screenshot(output + "/workflow.png");

    const refused = await inPage(`return await api("PATCH", "/items/${world.item}", { state_id: "${world.done}" });`);
    checks.handMoveRefusedWithoutRelease = refused.status >= 400 && JSON.stringify(refused.body).includes("a release is required");

    await session.navigate(`${baseUrl}/p/${world.key}/releases`, 2500);
    checks.releasesPageNamesTheMove = await waitFor(session,
      `document.querySelector('[data-release-shipping]')?.textContent.includes("Waiting for release → Done")`);
    await session.screenshot(output + "/releases.png");

    const shipped = await inPage(`
      await api("POST", "/releases", { project_id: "${world.projectId}", name: "1.0", version: "1.0.0", status: "released" });
      return (await api("GET", "/items/${world.item}")).body;`);
    checks.publishingShipsWithRelease = shipped.state?.id === world.done && shipped.release?.version === "1.0.0";
  } finally {
    if (world?.projectId) await inPage(`return (await api("DELETE", "/projects/${world.projectId}")).status;`).catch(() => null);
    await close();
  }
  process.exit(report(checks) ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
