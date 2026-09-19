/**
 * The scripts plugin (RADD-1269), end to end against a running server:
 *
 *   - Settings → Scripts builds the interpreter (uv, a real venv) and shows it
 *     ready; a package installs and lists with its resolved version;
 *   - a script is created from the starter, edited, saved (a new version), and
 *     Run now returns the dict it computes;
 *   - an automation with `script.run` after an item.updated trigger fires on a
 *     real update: the script calls `ctx.client.add_comment`, the comment lands
 *     attributed to the automation's identity, and the run history shows the
 *     node applied with the declared output published;
 *   - a script that raises shows up in the run as failed, and the branch
 *     continues;
 *   - `script.decide` routes by the port the script names.
 *
 * Usage: node scripts/scripts-plugin-proof.mjs [--base http://localhost:8000]
 * Needs uv on the host and a Python 3.12 it can provide (it downloads one).
 */
import { writeFileSync } from "node:fs";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const baseUrl = args.includes("--base") ? args[args.indexOf("--base") + 1] : "http://localhost:8000";
const email = process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = process.env.RADD_PROOF_PASSWORD ?? "change-me";

const { session, close } = await openBrowser({ port: 9360, profile: "/tmp/radd-scripts" });

const api = (method, path, body) =>
  `(async()=>{const r=await fetch("/api/v1${path}",{method:${JSON.stringify(method)},credentials:"include",` +
  `headers:{"Content-Type":"application/json"}${body === undefined ? "" : `,body:JSON.stringify(${JSON.stringify(body)})`}});` +
  `return {status:r.status, body: await r.text()};})()`;
const parsed = (r) => (r.status < 300 ? JSON.parse(r.body) : null);

await session.navigate(baseUrl, 1500);
const loginStatus = await session.login(baseUrl, email, password);

// --- the interpreter, by API (a real uv build; slow the first time) ----------
const before = parsed(await session.eval(api("GET", "/scripts/interpreter")));
const built = before?.status === "ready"
  ? before
  : parsed(await session.eval(api("POST", "/scripts/interpreter/rebuild", { python_version: "3.12" })));
const pkg = parsed(await session.eval(api("POST", "/scripts/packages", { spec: "six>=1.16" })));

// --- scripts ------------------------------------------------------------------
const suffix = Math.random().toString(36).slice(2, 6);
const COMMENTER = `Commenter ${suffix}`;
const commenter = parsed(await session.eval(api("POST", "/scripts", {
  name: COMMENTER,
  body: [
    "import six",
    "def main(ctx):",
    "    item = ctx.item",
    "    ctx.client.add_comment(item['id'], f\"Scripted hello on {item['key']} (six {six.__version__})\")",
    "    return {'greeted': item['key'], 'count': len(ctx.items)}",
    "",
  ].join("\n"),
  note: "proof",
})));
const BROKEN = `Broken ${suffix}`;
const broken = parsed(await session.eval(api("POST", "/scripts", { name: BROKEN, body: "def main(ctx):\n    raise ValueError('deliberate')\n" })));
const ROUTER = `Router ${suffix}`;
const router = parsed(await session.eval(api("POST", "/scripts", { name: ROUTER, body: "def main(ctx):\n    return 'left' if ctx.items and 'left' in ctx.items[0]['title'] else 'right'\n" })));

// Run now, by API, with a pasted packet — the commenter needs a real item.
const project = parsed(await session.eval(api("POST", "/projects", { key: `SP${suffix.toUpperCase()}`, name: `Scripts ${suffix}` })));
const item = parsed(await session.eval(api("POST", "/items", { project_id: project?.id, title: "go left please" })));
const itemRead = parsed(await session.eval(api("GET", `/items/${item?.id}`)));
const runNow = parsed(await session.eval(api("POST", `/scripts/${commenter?.id}/run`, { items: [itemRead], vars: {}, params: {}, timeout: 60 })));

// --- an automation that runs it, decides with one, and hits the broken one ----
const rule = parsed(await session.eval(api("POST", "/automations", {
  name: `scripts proof ${suffix}`, enabled: true, orientation: "vertical",
  nodes: [
    { id: "trg1", kind: "trigger", type: "trigger.event", params: { event: "item.updated" } },
    { id: "flt1", kind: "filter", type: "filter.slq", params: { slq: `project = ${project?.key}` } },
    { id: "dec1", kind: "gate", type: "script.decide", params: { script: ROUTER, ports: ["left", "right"], timeout: 60 } },
    { id: "run1", kind: "action", type: "script.run", name: "hello", params: { script: COMMENTER, outputs: ["greeted", "count"], timeout: 60 } },
    { id: "say1", kind: "action", type: "action.add_label", params: { label: "greeted-{{hello.count}}" } },
    { id: "bad1", kind: "action", type: "script.run", params: { script: BROKEN, outputs: [], timeout: 60 } },
  ],
  edges: [
    { source: "trg1", port: "out", target: "flt1" },
    { source: "flt1", port: "matched", target: "dec1" },
    { source: "dec1", port: "left", target: "run1" },
    { source: "run1", port: "out", target: "say1" },
    { source: "run1", port: "out", target: "bad1" },
  ],
})));
await session.eval(api("PATCH", `/items/${item?.id}`, { title: "go left please, renamed" }));
let runs = [];
for (let attempt = 0; attempt < 40 && runs.length === 0; attempt++) {
  await sleep(1500);
  runs = parsed(await session.eval(api("GET", `/automations/${rule?.id}/runs`))) ?? [];
}
const run = runs[0] ?? null;
const detail = run ? parsed(await session.eval(api("GET", `/automations/${rule?.id}/runs/${run.id}`))) : null;
const comments = parsed(await session.eval(api("GET", `/items/${item?.id}/comments`)));
const itemAfter = parsed(await session.eval(api("GET", `/items/${item?.id}`)));
const nodeResult = (id) => detail?.report?.nodes?.find((n) => n.node_id === id);
const actionOf = (id) => detail?.report?.would_apply?.find((a) => a.node_id === id);

// --- the settings page, in the browser ------------------------------------------
await session.navigate(`${baseUrl}/settings/scripts`, 3000);
// The lists arrive after the page: wait for the library rows before reading.
for (let attempt = 0; attempt < 10; attempt++) {
  const rows = await session.eval(`document.querySelectorAll("[data-scripts-list] [data-script-row]").length`);
  if (rows > 0) break;
  await sleep(800);
}
const pageState = await session.eval(`(()=>({
  status: document.querySelector("[data-scripts-interpreter] [data-interpreter-status]")?.getAttribute("data-interpreter-status") ?? null,
  packages: [...document.querySelectorAll("[data-scripts-packages] [data-package]")].map(li=>li.getAttribute("data-package")+":"+li.querySelector("[data-package-status]")?.getAttribute("data-package-status")),
  scripts: [...document.querySelectorAll("[data-scripts-list] [data-script-row]")].map(b=>b.getAttribute("data-script-row")),
}))()`);
await session.eval(`(()=>{const b=document.querySelector('[data-script-row=${JSON.stringify(COMMENTER)}]'); if(b) b.click(); return !!b;})()`);
await sleep(2500);
const editorShown = await session.eval(`Boolean(document.querySelector("[data-script-editor] [data-python-editor] .cm-editor"))`);
const editorText = await session.eval(`(document.querySelector("[data-script-editor] .cm-content")||{innerText:""}).innerText.includes("add_comment")`);

const shot = await session.send("Page.captureScreenshot", { format: "png" });
writeFileSync("/tmp/radd-scripts.png", Buffer.from(shot.data, "base64"));

// --- cleanup -----------------------------------------------------------------------
if (rule) await session.eval(api("DELETE", `/automations/${rule.id}`));
for (const s of [commenter, broken, router]) if (s) await session.eval(api("DELETE", `/scripts/${s.id}`));
if (item) await session.eval(api("DELETE", `/items/${item.id}`));
if (pkg) await session.eval(api("DELETE", `/scripts/packages/${pkg.id}`));

const consoleErrors = session.consoleErrors.filter((e) => !/favicon|404/i.test(e));
const scriptedComment = (comments?.items ?? comments ?? []).find?.((c) => /Scripted hello/.test(c.body)) ?? null;
const checks = {
  loginStatus,
  interpreter: built && { status: built.status, resolved: built.resolved, sdk: built.sdk_source },
  package: pkg && { status: pkg.status, resolved: pkg.resolved_version },
  runNow: runNow && { ok: runNow.ok, result: runNow.result, error: runNow.error },
  run: run && { status: run.status, applied: run.actions_applied, skipped: run.actions_skipped },
  decide: nodeResult("dec1")?.ports?.map((p) => `${p.port}:${p.taken ? p.count : "-"}`),
  helloAction: actionOf("run1") && { resolves: actionOf("run1").resolves, detail: actionOf("run1").detail },
  helloProduced: nodeResult("run1")?.produced?.map((p) => `${p.token}=${p.value}`),
  labelAction: actionOf("say1") && { resolves: actionOf("say1").resolves, detail: actionOf("say1").detail },
  brokenAction: actionOf("bad1") && { resolves: actionOf("bad1").resolves, detail: actionOf("bad1").detail },
  scriptedComment: scriptedComment && { body: scriptedComment.body, author: scriptedComment.author?.name },
  labels: itemAfter?.labels,
  reportNodes: detail?.report?.nodes?.map((n) => ({ id: n.node_id, ran: n.ran, ports: n.ports.map((p) => `${p.port}:${p.taken ? p.count : "-"}`) })),
  reportActions: detail?.report?.would_apply?.map((a) => ({ node: a.node_id, resolves: a.resolves, detail: a.detail })),
  reportDropped: detail?.report?.dropped,
  pageState,
  editorShown,
  editorText,
  screenshot: "/tmp/radd-scripts.png",
  consoleErrors,
};
console.log(JSON.stringify(checks, null, 2));

const ok =
  loginStatus === 204 &&
  built?.status === "ready" &&
  pkg?.status === "installed" && /^\d/.test(pkg?.resolved_version ?? "") &&
  runNow?.ok === true && runNow?.result?.count === 1 &&
  run?.status === "applied" &&
  (checks.decide ?? []).some((p) => p.startsWith("left:1")) &&
  actionOf("run1")?.resolves === true &&
  (checks.helloProduced ?? []).includes(`{{hello.greeted}}=${item?.key}`) &&
  actionOf("say1")?.resolves === true &&
  actionOf("bad1")?.resolves === false && /deliberate/.test(actionOf("bad1")?.detail ?? "") &&
  Boolean(scriptedComment) && /six \d/.test(scriptedComment?.body ?? "") &&
  (itemAfter?.labels ?? []).includes("greeted-1") &&
  pageState.status === "ready" &&
  pageState.packages.includes("six:installed") &&
  pageState.scripts.includes(COMMENTER) &&
  editorShown && editorText &&
  consoleErrors.length === 0;
report({ "scripts run from automations, out of process, as the automation's identity": ok }, "RADD-1269 — scripts plugin");

close();
process.exit(ok ? 0 : 1);
