/**
 * RADD-1489 against a RUNNING stack (not CI): seeds two throwaway projects, an epic in one with
 * children in both, and walks the four surfaces the wave changed — the epic page, a project board
 * grouped by epic, the epic's all-projects board, the child's rail — taking a screenshot of each;
 * checks the three server rules over the API (a cross-project subtask is refused, a typed key links
 * the project it names, a subtask never moves alone); then deletes both projects.
 *
 *   RADD_PROOF_COOKIE_FILE=<file holding a radd_session cookie>  RADD_PROOF_BASE_URL=http://127.0.0.1:8000
 */
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { openBrowser, outputPath, until } from "./lib/cdp.mjs";

const baseUrl = process.env.RADD_PROOF_BASE_URL || "http://127.0.0.1:8000";
const cookieFile = process.env.RADD_PROOF_COOKIE_FILE;
if (!cookieFile) throw Error("Set RADD_PROOF_COOKIE_FILE to a file containing a local radd_session cookie.");
const stamp = Date.now().toString(36).slice(-4).toUpperCase();
const KEYS = { dev: `XD${stamp}`, td: `XT${stamp}` };

const api = `const api = async (method, path, body) => {
  const r = await fetch('/api/v1' + path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text(); let data = null; try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  return { status: r.status, data };
};`;

let browser;
const checks = [];
const made = { projects: [] };
try {
  browser = await openBrowser({ port: 18875, profile: await mkdtemp("/tmp/radd-cross-project-live-"), scale: 1 });
  const s = browser.session;
  await s.send("Network.setCookie", { name: "radd_session", value: (await readFile(cookieFile, "utf8")).trim(), url: baseUrl, httpOnly: true });
  await s.navigate(`${baseUrl}/`);
  const call = async (method, path, body) => s.eval(`(async () => { ${api} return api(${JSON.stringify(method)}, ${JSON.stringify(path)}, ${body === undefined ? "undefined" : JSON.stringify(body)}); })()`);
  const ok = async (method, path, body) => { const r = await call(method, path, body); assert(r.status < 300, `${method} ${path} -> ${r.status} ${JSON.stringify(r.data).slice(0, 200)}`); return r.data; };
  const has = (selector) => s.eval(`!!document.querySelector(${JSON.stringify(selector)})`);
  const text = (selector) => s.eval(`document.querySelector(${JSON.stringify(selector)})?.textContent?.trim() ?? null`);
  const bodyHas = (phrase) => s.eval(`document.body.innerText.includes(${JSON.stringify(phrase)})`);

  // --- seed ---
  const dev = await ok("POST", "/projects", { key: KEYS.dev, name: "Cross DEV" }); made.projects.push(dev.id);
  const td = await ok("POST", "/projects", { key: KEYS.td, name: "Cross TD" }); made.projects.push(td.id);
  const epic = await ok("POST", "/items", { project_id: dev.id, kind: "epic", title: "Colour pipeline rework" });
  const devIssue = await ok("POST", "/items", { project_id: dev.id, title: "Rewrite the OCIO config loader", parent_id: epic.id });
  const tdOne = await ok("POST", "/items", { project_id: td.id, title: "Re-grade the lookdev turntables", parent_id: epic.id });
  const tdTwo = await ok("POST", "/items", { project_id: td.id, title: "Validate the new LUTs in Nuke", parent_id: epic.id });
  const tdStep = await ok("POST", "/items", { project_id: td.id, kind: "subtask", title: "Export the LUT set", parent_id: tdOne.id });
  const view = await ok("POST", "/views", { project_id: dev.id, name: "By epic", view_type: "board", group_by: "epic" });
  checks.push(`seeded ${epic.key} with ${devIssue.key}, ${tdOne.key}, ${tdTwo.key} (+ ${tdStep.key})`);

  // --- API rules ---
  const refused = await call("POST", "/items", { project_id: td.id, kind: "subtask", title: "a TD step under a DEV issue", parent_id: devIssue.id });
  assert.equal(refused.status, 409, `cross-project subtask answered ${refused.status}`);
  assert.match(JSON.stringify(refused.data), /lives in its parent's project/);
  checks.push("a subtask under an issue in another project is refused with the rule");
  const linked = await ok("POST", `/items/${tdTwo.id}/links`, { target_key: devIssue.key.toLowerCase(), link_type: "blocks" });
  assert(linked.links.outgoing.some((l) => l.item.key === devIssue.key), "typed key did not link the DEV issue");
  checks.push("a typed key links the project it names");
  const move = await ok("POST", "/items/bulk-move", { item_ids: [tdStep.id], target_project_id: dev.id });
  assert.deepEqual(move.moved, []);
  assert.equal(move.skipped[0]?.reason, "subtask_follows_parent");
  checks.push("a subtask selected without its issue does not move, and says why");

  // --- the epic page ---
  await s.navigate(`${baseUrl}/issues/${epic.key}`);
  await until(s, async () => has('[data-foreign-children="3"]'), "epic page never counted the TD children");
  assert.equal(await text('[data-foreign-children="3"]'), `3 in ${KEYS.td}`);
  assert(await has("[data-open-epic-board]"), "no Open as board");
  await s.screenshot(outputPath("radd-live-epic-page.png"));
  checks.push("the epic page says three descendants live in TD and offers Open as board");

  // --- the DEV board grouped by epic ---
  await s.navigate(`${baseUrl}/p/${KEYS.dev}/v/${view.id}`);
  await until(s, async () => has('[data-foreign-children="3"] a'), "DEV board's epic header has no chip");
  assert.equal(await text('[data-foreign-children="3"] a'), `3 more in ${KEYS.td}`);
  await s.screenshot(outputPath("radd-live-board-chip.png"));
  checks.push("the DEV board's epic group says 3 more in TD");

  // --- the epic board ---
  await s.click('[data-foreign-children="3"] a');
  await until(s, async () => (await s.eval("location.pathname")) === `/e/${epic.key}/board`, "chip did not open the epic board");
  await until(s, async () => bodyHas(`${KEYS.td} · Cross TD`) && bodyHas(`${KEYS.dev} · Cross DEV`), "epic board lanes not labelled by project");
  await until(s, async () => bodyHas(tdOne.title) && bodyHas(devIssue.title), "epic board lacks a card from one of the projects");
  // Four descendants (three in TD counting the subtask, one in DEV) and not the epic: the header's count.
  await until(s, async () => bodyHas("4 issues"), "epic board count is not the four descendants");
  await s.screenshot(outputPath("radd-live-epic-board.png"));
  checks.push("the epic board shows both projects' work in one screen");

  // --- the TD child's rail: its epic is in DEV, plainly ---
  await s.navigate(`${baseUrl}/issues/${tdOne.key}`);
  await until(s, async () => has(`[data-parent-current="${epic.key}"]`), "TD issue's rail does not show its DEV epic");
  await s.screenshot(outputPath("radd-live-child-rail.png"));
  checks.push("a TD issue's rail shows its DEV epic by key");

  console.log(JSON.stringify({ passed: true, checks }));
} catch (error) {
  if (browser) await browser.session.screenshot(outputPath("radd-live-failure.png"));
  throw error;
} finally {
  if (browser) {
    for (const id of made.projects) {
      const r = await browser.session.eval(`(async () => { ${api} return api('DELETE', '/projects/${id}'); })()`);
      if (r.status >= 300) console.error(`cleanup: DELETE /projects/${id} -> ${r.status}`);
    }
    await browser.close();
  }
}
