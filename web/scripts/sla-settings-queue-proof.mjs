/**
 * Browser proof for RADD-1396: a project's SLA settings page and the triage queue view type are
 * the slas plugin's — the page is a `project.settings.page` contribution listed by the plugin's
 * manifest nav entry, and the queue is a plugin view type the host's list draws over the plugin's
 * urgency-ordered rows. The host holds no SLA code. Against the REAL backend:
 *
 *   1. over REST: a throwaway project, a DISABLED policy (response 1h, resolution 8h, for blocker,
 *      high and normal), four issues — A normal, B normal, C high, D low (no policy matches D) —
 *      and a `slas.queue` view; a fixture helper backdates B by 3h and C by 30m, because a clock
 *      starts at the issue's created_at (this proof's backend runs without workers);
 *   2. settings: the project-settings nav lists "SLAs" (the slas manifest's entry), and
 *      /p/KEY/settings/sla renders the page from /plugins/slas/; editing the policy's warning to
 *      15m through the form is a PATCH the API reads back, and the policy's summary says so;
 *   3. queue: with the policy ENABLED only for this step (enabled, rendered, disabled again — a
 *      running engine elsewhere gets seconds, not a sweep of work), the sidebar lists the view in
 *      its "Queues" section with a live count of 4 and nowhere else; the view's rows come from
 *      GET /sla-queue-items in the spec-64 order — the breached B, then C (due in ~30m), then A
 *      (~60m), then D (no timers) — which is not the list's rank order; the SLA column shows
 *      Breached, two countdowns and a dash; no row is draggable (the plugin's order stands);
 *   4. no host chunk carries the SLA settings or queue UI: every web/dist/assets/*.js is read for
 *      the page's copy and the endpoints, and the slas remote / the manifest do carry them;
 *   5. no console errors; the view and the project are deleted again (issues and policy cascade).
 *
 * Usage (from web/): node scripts/sla-settings-queue-proof.mjs <baseUrl> [email] [password]
 * The backend must come from this checkout; the fixture helper runs in ../server against the
 * database its settings name (RADD_DATABASE_URL), which must be the one that backend serves.
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8116", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9516;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-sla-settings-queue-proof-profile");
const SHOTS = process.env.RADD_PROOF_SHOTS ?? TMP;
const HERE = dirname(fileURLToPath(import.meta.url));
const SERVER = resolve(HERE, "../../server");
const key = `SQ${Date.now().toString(36).slice(-4).toUpperCase()}`;
const POLICY = "Queue proof";
const POLICY_ROW = JSON.stringify(`[data-sla-policy="${POLICY}"]`);
const QUEUE = "Triage queue proof";

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });

async function waitFor(session, expression, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(250);
  }
  return session.eval(expression);
}

const API = `const api = async (method, path, body) => { const r = await fetch("/api/v1" + path, { method,
  headers: { "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text(); return { status: r.status, body: text ? JSON.parse(text) : null }; };`;

// A clock starts at the issue's created_at: move two of them into the past.
const BACKDATE = `
import asyncio, sys, uuid
from datetime import timedelta
from sqlalchemy import update
from radd.config import settings
from radd.kernel import load_plugins
load_plugins(settings.modules)
from radd.clock import utcnow
from radd.db import SessionLocal
from radd.modules.items.models import WorkItem

async def main(breached_id, sooner_id):
    async with SessionLocal() as session:
        now = utcnow()
        for item_id, age in ((breached_id, timedelta(hours=3)), (sooner_id, timedelta(minutes=30))):
            await session.execute(update(WorkItem).where(WorkItem.id == uuid.UUID(item_id)).values(created_at=now - age))
        await session.commit()

asyncio.run(main(*sys.argv[1:]))
`;

/** "59m left" / "1h 0m left" → minutes; anything else stays as it is. */
const minutesOf = (label) => {
  const match = /^(?:(\d+)d|(?:(\d+)h )?(\d+)m) left$/.exec(label ?? "");
  if (!match) return label;
  return match[1] ? Number(match[1]) * 1440 : Number(match[2] ?? 0) * 60 + Number(match[3]);
};

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1000, scale: 1 });
const send = session.send;
let world = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  // 1. The world, over REST.
  world = await session.eval(`(async () => { ${API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "SLA settings + queue proof" });
    const id = project.body.id;
    const policy = await api("POST", "/sla-policies", { project_id: id, name: ${JSON.stringify(POLICY)},
      priorities: ["blocker", "high", "normal"], response_minutes: 60, resolution_minutes: 480, enabled: false });
    const made = [];
    for (const [title, priority] of [["A: fresh", "normal"], ["B: three hours old", "normal"], ["C: half an hour old", "high"], ["D: no policy", "low"]]) {
      made.push(await api("POST", "/items", { project_id: id, title: "Queue proof " + title, priority }));
    }
    const queue = await api("POST", "/views", { project_id: id, name: ${JSON.stringify(QUEUE)}, view_type: "slas.queue", query: "" });
    return { projectId: id, policyId: policy.body?.id, queueId: queue.body?.id, queueType: queue.body?.view_type,
      items: made.map((r) => ({ id: r.body?.id, key: r.body?.key })),
      status: [project.status, policy.status, ...made.map((r) => r.status), queue.status] };
  })()`);
  check("a throwaway project, a disabled policy, four issues and a slas.queue view exist",
    world.status.every((s) => s === 201) && world.queueType === "slas.queue", JSON.stringify([world.status, world.queueType]));
  const [A, B, C, D] = world.items;
  execFileSync("uv", ["run", "python", "-c", BACKDATE, B.id, C.id], { cwd: SERVER, stdio: ["ignore", "inherit", "inherit"] });

  // 2. Settings: the plugin's page, listed by its manifest entry.
  await session.navigate(`${baseUrl}/p/${key}/settings/sla`, 2500);
  await waitFor(session, `!!document.querySelector(${POLICY_ROW})`);
  const nav = await session.eval(`(() => { const link = document.querySelector('nav[aria-label="Project settings sections"] a[data-plugin-nav="slas"]');
    return link ? { text: link.textContent.trim(), href: link.getAttribute("href"), active: link.classList.contains("active") } : null; })()`);
  check("the project-settings nav lists SLAs, owned by slas, and it is the open page",
    nav?.text === "SLAs" && nav.href === `/p/${key}/settings/sla` && nav.active, JSON.stringify(nav));
  const loaded = await session.eval(`performance.getEntriesByType("resource").map((entry) => new URL(entry.name).pathname)`);
  check("the page is loaded from /plugins/slas/", loaded.includes("/plugins/slas/remoteEntry.js"),
    JSON.stringify(loaded.filter((p) => p.startsWith("/plugins/"))));
  const listed = await session.eval(`document.querySelector(${POLICY_ROW})?.textContent ?? ""`);
  check("the policy is listed with its summary, disabled", listed.includes("Blocker/High/Normal")
    && listed.includes("response 1h") && listed.includes("resolution 8h") && listed.includes("Disabled"), listed);

  await clickAt(send, `button[aria-label="Edit ${POLICY}"]`);
  await waitFor(session, `!!document.querySelector('[data-sla-policy-form="edit"]')`);
  await session.eval(`(() => {
    const form = document.querySelector('[data-sla-policy-form="edit"]');
    const input = [...form.querySelectorAll("label")].find((l) => l.textContent.trim() === "Warn before breach")?.parentElement?.querySelector("input");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, "15m");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  })()`);
  await sleep(200);
  await clickAt(send, '[data-sla-policy-form="edit"] button[type=submit]', (t) => t.trim().startsWith("Save changes"));
  await waitFor(session, `!document.querySelector('[data-sla-policy-form="edit"]')`);
  const saved = await session.eval(`(async () => { ${API}
    return (await api("GET", "/sla-policies?project_id=" + ${JSON.stringify(world.projectId)})).body; })()`);
  const summary = await waitFor(session, `(() => { const t = document.querySelector(${POLICY_ROW})?.textContent ?? "";
    return t.includes("warn 15m before") ? t : ""; })()`);
  check("the edit is a PATCH of the same policy the API reads back (warning 15m, still disabled)",
    saved?.length === 1 && saved[0].id === world.policyId && saved[0].warning_minutes === 15 && saved[0].enabled === false,
    JSON.stringify(saved?.map((p) => [p.id === world.policyId, p.warning_minutes, p.enabled])));
  check("the policy's summary shows the edit", Boolean(summary), summary);
  await session.screenshot(resolve(SHOTS, "sla-settings-queue-proof-settings.png"));

  // 3. The queue, with the policy enabled only while it renders.
  const enabled = await session.eval(`(async () => { ${API}
    return (await api("PATCH", "/sla-policies/" + ${JSON.stringify(world.policyId)}, { enabled: true })).status; })()`);
  check("the policy is enabled for the queue step", enabled === 200, String(enabled));
  const truth = await session.eval(`(async () => { ${API}
    const q = "project_id=" + ${JSON.stringify(world.projectId)};
    const rows = await api("GET", "/sla-queue-items?" + q + "&limit=50&offset=0");
    const ranked = await api("GET", "/items?" + q + "&limit=50&offset=0");
    return { queue: rows.body.map((i) => i.key), ranked: ranked.body.map((i) => i.key) }; })()`);
  const expected = [B.key, C.key, A.key, D.key];
  check("GET /sla-queue-items orders breached, then soonest due, then untimed (spec 64)",
    JSON.stringify(truth.queue) === JSON.stringify(expected), `${JSON.stringify(truth.queue)} vs ${JSON.stringify(expected)}`);
  check("…which is not the list's own (rank) order", JSON.stringify(truth.ranked) !== JSON.stringify(expected),
    JSON.stringify(truth.ranked));

  await session.navigate(`${baseUrl}/p/${key}/v/${world.queueId}`, 2500);
  await waitFor(session, `document.querySelectorAll('[data-sla-cell]').length === 3`);
  const rows = await session.eval(`(() => {
    const header = [...document.querySelectorAll('main [data-column]')].map((el) => el.dataset.column);
    const seen = new Set();
    return [...document.querySelectorAll('main li')].flatMap((row) => {
      const itemKey = row.textContent.match(/${key}-\\d+/)?.[0];
      if (!itemKey || seen.has(itemKey)) return [];
      seen.add(itemKey);
      const cell = [...row.children].filter((el) => el.style.flexBasis)[header.indexOf('slas.timer')];
      return [[itemKey, cell ? cell.querySelector('[data-sla-chip]')?.textContent ?? cell.textContent.trim() : null]];
    }); })()`);
  check("the queue renders its rows in the endpoint's order", JSON.stringify(rows.map((r) => r[0])) === JSON.stringify(expected),
    JSON.stringify(rows));
  const timers = Object.fromEntries(rows);
  const soon = minutesOf(timers[C.key]);
  const later = minutesOf(timers[A.key]);
  check("the SLA column shows Breached, two countdowns (C sooner than A) and a dash",
    timers[B.key] === "Breached" && typeof soon === "number" && typeof later === "number" && soon < later
      && soon >= 25 && soon <= 31 && later >= 55 && later <= 61 && timers[D.key] === "—", JSON.stringify(timers));
  const resources = await session.eval(`performance.getEntriesByType("resource").map((entry) => new URL(entry.name).pathname)`);
  check("the rows came from GET /sla-queue-items", resources.includes("/api/v1/sla-queue-items"),
    JSON.stringify(resources.filter((p) => p.includes("sla"))));
  check("no row is draggable — the plugin's order stands",
    (await session.eval(`document.querySelectorAll('main li [draggable="true"], main li[draggable="true"]').length`)) === 0);
  const sidebar = await waitFor(session, `(() => {
    const section = document.querySelector('[data-view-type-section="slas.queue"]');
    const link = [...(section?.querySelectorAll("a") ?? [])].find((a) => a.textContent.includes(${JSON.stringify(QUEUE)}));
    const badge = link?.querySelector("span.ml-auto")?.textContent.trim();
    return link && badge ? { heading: section.textContent.includes("Queues"), badge, href: link.getAttribute("href") } : null; })()`);
  check("the sidebar lists the queue in its Queues section with a live count of 4",
    sidebar?.heading && sidebar.badge === "4" && sidebar.href === `/p/${key}/v/${world.queueId}`, JSON.stringify(sidebar));
  const elsewhere = await session.eval(`[...document.querySelectorAll('aside a')].filter((a) => a.textContent.includes(${JSON.stringify(QUEUE)})
    && !a.closest('[data-view-type-section]')).length`);
  check("…and not among the project's ordinary views", elsewhere === 0, String(elsewhere));
  await session.screenshot(resolve(SHOTS, "sla-settings-queue-proof-queue.png"));
  const disabled = await session.eval(`(async () => { ${API}
    return (await api("PATCH", "/sla-policies/" + ${JSON.stringify(world.policyId)}, { enabled: false })).status; })()`);
  check("the policy is disabled again", disabled === 200, String(disabled));

  // 4. The UI is the remote's: no host chunk carries it, and its owner does.
  const assets = resolve(HERE, "../dist/assets");
  const settingsCopy = ["No SLA policies for this project yet.", "Business hours start", "Response is met when",
    "/sla-policies", "data-sla-policy-form"];
  const queueWire = ["/sla-queue-items", "Queue (triage list)", "slas.queue", "slas.timer"];
  const hostHits = readdirSync(assets).filter((f) => f.endsWith(".js")).flatMap((f) => {
    const text = readFileSync(resolve(assets, f), "utf8");
    return [...settingsCopy, ...queueWire].filter((marker) => text.includes(marker)).map((marker) => `${f}: ${marker}`);
  });
  const remote = readFileSync(resolve(HERE, "../../server/src/radd/modules/slas/ui/dist/remoteEntry.js"), "utf8");
  check("no host chunk carries the SLA settings page or the queue", hostHits.length === 0, JSON.stringify(hostHits));
  check("the slas remote carries the settings page", settingsCopy.every((marker) => remote.includes(marker)),
    JSON.stringify(settingsCopy.filter((marker) => !remote.includes(marker))));
  const manifest = await session.eval(`(async () => { ${API} return (await api("GET", "/capabilities")).body; })()`);
  const queueType = manifest.view_types.find((t) => t.key === "slas.queue");
  check("the slas manifest declares the queue: a list surface over /sla-queue-items, in the Queues section",
    queueType?.list_surface?.rows_path === "/sla-queue-items" && queueType.sidebar_section === "Queues"
      && queueType.list_surface.columns.includes("slas.timer")
      && manifest.nav.some((n) => n.section === "project_settings" && n.path === "sla" && n.plugin === "slas"),
    JSON.stringify(queueType));

  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  // 5. Clean up: the issues and the policy cascade with the project.
  if (world?.projectId) {
    const cleaned = await session.eval(`(async () => { ${API}
      if (${JSON.stringify(world.policyId ?? "")}) await api("PATCH", "/sla-policies/" + ${JSON.stringify(world.policyId ?? "")}, { enabled: false });
      const v = ${JSON.stringify(world.queueId ?? "")} ? await api("DELETE", "/views/" + ${JSON.stringify(world.queueId ?? "")}) : { status: 0 };
      const p = await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)});
      const gone = await api("GET", "/projects/by-key/" + ${JSON.stringify(key)});
      return [v.status, p.status, gone.status];
    })()`);
    check("the view and the project are deleted again", cleaned.join() === "204,204,404", JSON.stringify(cleaned));
  }
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "SLA settings page + queue views (RADD-1396)", key },
);
process.exit(failed ? 1 : 0);
