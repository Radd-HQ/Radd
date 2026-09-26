/**
 * Browser proof for RADD-1386: the SLA report is the slas plugin's own — its endpoint, its
 * numbers and its UI — and it draws with reporting's chart kit through the reporting contract.
 * Against the REAL backend:
 *
 *   1. a throwaway project with a DISABLED policy (so a running engine never re-stamps it), two
 *      issues, and a dashboard carrying a "Service desk SLA" widget — all over REST;
 *   2. what the workers would write — the engine's met/breached stamps and two answered
 *      surveys — through the app's own services (this proof runs its backend without workers);
 *   3. the old /reports/sla is gone; GET /sla-report returns the fixture;
 *   4. the project reports page, the global reports page and the dashboard widget each render the
 *      section from /plugins/slas/, with tiles equal to a direct GET of the endpoint;
 *   5. no console errors; the dashboard and project are deleted again (the fixture cascades).
 *
 * Usage (from web/): node scripts/sla-report-proof.mjs <baseUrl> [email] [password]
 * The backend must come from this checkout; the fixture helper runs in ../server against the
 * database its settings name, which must be the one that backend serves.
 */
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const PORT = 9508;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-sla-report-proof-profile");
const SHOT = process.env.RADD_PROOF_SHOT ?? resolve(TMP, "sla-report-proof.png");
const SERVER = resolve(dirname(fileURLToPath(import.meta.url)), "../../server");
const key = `SR${Date.now().toString(36).slice(-4).toUpperCase()}`;

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

// Stands in for the SLA engine's sweep and the csat sender: the same rows, written by the app.
const STAMP = `
import asyncio, sys, uuid
from datetime import timedelta
from radd.config import settings
from radd.kernel import load_plugins
load_plugins(settings.modules)
from radd.db import SessionLocal
from radd.modules.csat import service as csat
from radd.modules.csat.schemas import PublicCsatSubmit
from radd.modules.items import service as items
from radd.modules.slas.models import SlaItemState

async def main(policy_id, key, met_id, late_id):
    async with SessionLocal() as session:
        found = await items.items_by_ids(session, [uuid.UUID(met_id), uuid.UUID(late_id)])
        met, late = found[uuid.UUID(met_id)], found[uuid.UUID(late_id)]
        policy = uuid.UUID(policy_id)
        session.add(SlaItemState(item_id=met.id, policy_id=policy,
            response_met_at=met.created_at + timedelta(minutes=30),
            resolution_met_at=met.created_at + timedelta(hours=4)))
        session.add(SlaItemState(item_id=late.id, policy_id=policy,
            response_breached_at=late.created_at + timedelta(minutes=61)))
        for item, rating in ((met, 5), (late, 3)):
            survey = await csat.create_survey(session, item_id=item.id, item_key=f"{key}-{item.number}")
            await csat.record_response(session, survey.token, PublicCsatSubmit(rating=rating))
        await session.commit()

asyncio.run(main(*sys.argv[1:]))
`;

/** The tiles the card must show for a report — the card's own arithmetic, restated as the oracle. */
function expectedTiles(sla) {
  const sum = (pick) => sla.buckets.reduce((total, bucket) => total + pick(bucket), 0);
  const weighted = (value, count) => {
    let total = 0;
    let samples = 0;
    for (const bucket of sla.buckets) {
      if (value(bucket) === null) continue;
      total += value(bucket) * count(bucket);
      samples += count(bucket);
    }
    return samples > 0 ? total / samples : null;
  };
  const duration = (seconds) => {
    if (seconds === null) return "—";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    const hours = Math.floor(minutes / 60);
    return hours < 48 ? `${hours}h ${minutes % 60}m` : `${Math.floor(hours / 24)}d ${hours % 24}h`;
  };
  const items = sum((b) => b.items);
  const breached = sum((b) => Math.round(b.breach_rate * b.items));
  const csat = weighted((b) => b.csat_avg, (b) => b.csat_count);
  return [
    ["Breach rate", `${Math.round((items > 0 ? breached / items : 0) * 100)}%`],
    ["Avg first response", duration(weighted((b) => b.avg_response_seconds, (b) => b.response_met))],
    ["Avg resolution", duration(weighted((b) => b.avg_resolution_seconds, (b) => b.resolution_met))],
    [`CSAT (${sum((b) => b.csat_count)})`, csat === null ? "—" : `${csat.toFixed(1)} ★`],
  ];
}

const tilesIn = (scope) => `[...document.querySelectorAll('${scope} [data-sla-report] [data-sla-tile]')]
  .map((tile) => [tile.dataset.slaTile, tile.lastElementChild.textContent.trim()])`;
const chartsIn = (scope) => `(() => { const root = document.querySelector('${scope} [data-sla-report]');
  return { trend: Boolean(root?.querySelector('svg[aria-label="SLA targets met vs breached per week"]')),
    csat: Boolean(root?.querySelector('svg[aria-label="Average CSAT rating per week"]')),
    legend: [...(root?.querySelectorAll("ul li") ?? [])].map((li) => li.textContent.trim()) }; })()`;

const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
let world = null;
try {
  await session.navigate(`${baseUrl}/login`, 800);
  const status = await session.login(baseUrl, email, password);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  // 1. The world, over REST.
  world = await session.eval(`(async () => { ${API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "SLA report proof" });
    const id = project.body.id;
    const policy = await api("POST", "/sla-policies", { project_id: id, name: "Proof", response_minutes: 60,
      resolution_minutes: 480, enabled: false });
    const met = await api("POST", "/items", { project_id: id, title: "SLA proof: met both targets" });
    const late = await api("POST", "/items", { project_id: id, title: "SLA proof: first response late" });
    const dashboard = await api("POST", "/dashboards", { name: "SLA report proof " + ${JSON.stringify(key)} });
    const widget = await api("POST", "/dashboards/" + dashboard.body.id + "/widgets", { widget_type: "report_sla",
      title: "Proof SLA", width: 12, height: 640, config: { project_id: id, weeks: 12 } });
    return { projectId: id, policyId: policy.body?.id, metId: met.body?.id, lateId: late.body?.id,
      dashboardId: dashboard.body?.id,
      status: [project.status, policy.status, met.status, late.status, dashboard.status, widget.status] };
  })()`);
  check("a throwaway project, disabled policy, two issues and an SLA dashboard widget exist",
    world.status.join() === "201,201,201,201,201,201", JSON.stringify(world.status));

  // 2. The rows the workers would have written.
  execFileSync("uv", ["run", "python", "-c", STAMP, world.policyId, key, world.metId, world.lateId],
    { cwd: SERVER, stdio: ["ignore", "inherit", "inherit"] });

  // 3. The endpoint moved.
  const direct = await session.eval(`(async () => { ${API}
    const project = await api("GET", "/sla-report?weeks=12&project_id=" + ${JSON.stringify(world.projectId)});
    const everywhere = await api("GET", "/sla-report?weeks=12");
    const old = await api("GET", "/reports/sla?weeks=12&project_id=" + ${JSON.stringify(world.projectId)});
    return { project: project.body, everywhere: everywhere.body, status: [project.status, everywhere.status, old.status] };
  })()`);
  check("the old /reports/sla answers 404", direct.status[2] === 404, JSON.stringify(direct.status));
  const sums = (sla) => ["items", "response_met", "response_breached", "resolution_met", "csat_count"]
    .map((field) => sla.buckets.reduce((total, bucket) => total + bucket[field], 0));
  check("GET /sla-report returns the fixture (2 issues, 1+1 met, 1 breached, 2 ratings)",
    direct.status[0] === 200 && sums(direct.project).join() === "2,1,1,1,2", JSON.stringify(sums(direct.project)));

  // 4a. The project's reports page.
  await session.navigate(`${baseUrl}/p/${key}/reports`, 2500);
  await waitFor(session, `document.querySelectorAll('[data-sla-report] [data-sla-tile]').length === 4`);
  const fromRemote = await session.eval(`performance.getEntriesByType("resource").map((entry) => entry.name)
    .filter((name) => name.includes("/plugins/slas/"))`);
  // The loader appends a cache-busting `?v=` — compare the path.
  check("the section is loaded from /plugins/slas/",
    fromRemote.some((name) => new URL(name).pathname === "/plugins/slas/remoteEntry.js"), JSON.stringify(fromRemote));
  const projectTiles = await session.eval(tilesIn("main"));
  const wanted = expectedTiles(direct.project);
  check("project page: the tiles equal GET /sla-report", JSON.stringify(projectTiles) === JSON.stringify(wanted),
    `${JSON.stringify(projectTiles)} vs ${JSON.stringify(wanted)}`);
  check("project page: the fixture reads 50% · 30m · 4h 0m · CSAT (2) 4.0 ★",
    JSON.stringify(wanted) === JSON.stringify([["Breach rate", "50%"], ["Avg first response", "30m"],
      ["Avg resolution", "4h 0m"], ["CSAT (2)", "4.0 ★"]]), JSON.stringify(wanted));
  const charts = await session.eval(chartsIn("main"));
  check("project page: the trend, CSAT chart and legend come from reporting's kit",
    charts.trend && charts.csat && charts.legend.join() === "Met,Breached", JSON.stringify(charts));
  // The page scrolls inside the shell, not the document: bring the section into the viewport.
  await session.eval(`document.querySelector('[data-sla-report]').scrollIntoView({ block: "start" })`);
  await sleep(300);
  await session.screenshot(SHOT);

  // 4b. The global reports page.
  await session.navigate(`${baseUrl}/reports`, 2500);
  await waitFor(session, `document.querySelectorAll('[data-sla-report] [data-sla-tile]').length === 4`);
  const globalTiles = await session.eval(tilesIn("main"));
  check("global page: the tiles equal GET /sla-report (every readable project)",
    JSON.stringify(globalTiles) === JSON.stringify(expectedTiles(direct.everywhere)),
    `${JSON.stringify(globalTiles)} vs ${JSON.stringify(expectedTiles(direct.everywhere))}`);

  // 4c. The dashboard widget.
  await session.navigate(`${baseUrl}/dashboards/${world.dashboardId}`, 2500);
  await waitFor(session, `document.querySelectorAll('.dashboard-widget [data-sla-report] [data-sla-tile]').length === 4`);
  const widgetTiles = await session.eval(tilesIn(".dashboard-widget"));
  check("dashboard widget: drawn by slas, tiles equal GET /sla-report",
    JSON.stringify(widgetTiles) === JSON.stringify(wanted), JSON.stringify(widgetTiles));
  const widgetCharts = await session.eval(chartsIn(".dashboard-widget"));
  check("dashboard widget: the charts render inside the widget", widgetCharts.trend && widgetCharts.csat,
    JSON.stringify(widgetCharts));

  check("no console errors", session.consoleErrors.length === 0, JSON.stringify(session.consoleErrors));
} finally {
  // 5. Clean up: the fixture rows cascade with the project's issues and policy.
  if (world?.projectId) {
    const cleaned = await session.eval(`(async () => { ${API}
      const d = ${JSON.stringify(world.dashboardId ?? null)} ? await api("DELETE", "/dashboards/" + ${JSON.stringify(world.dashboardId)}) : { status: 0 };
      const p = await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)});
      const gone = await api("GET", "/sla-report?project_id=" + ${JSON.stringify(world.projectId)});
      return [d.status, p.status, gone.status];
    })()`);
    check("the dashboard and project are deleted again", cleaned.join() === "204,204,404", JSON.stringify(cleaned));
  }
  await close();
}
const failed = report(
  Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])),
  { proof: "SLA report (RADD-1386)" },
);
process.exit(failed ? 1 : 0);
