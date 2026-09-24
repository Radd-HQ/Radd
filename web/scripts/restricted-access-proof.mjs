/**
 * Proves RADD-768: access control shapes the UI instead of refusing it.
 *
 * Walks the app signed in as a LOW-PRIVILEGE account and asserts two things the
 * whole epic reduces to:
 *
 *   1. **No 403 reaches the person.** Every refusal the actor meets is a bug in
 *      the interface, not in enforcement — enforcement is working, that is the
 *      problem. Measured by patching `fetch` and recording every 403 with the
 *      stack that caused it, because a URL alone does not say who asked (the
 *      RADD-769 finding: two of them came from a plugin remote that `grep
 *      web/src` cannot see).
 *
 *   2. **Every enabled control is one the actor may actually use.** This is the
 *      half that cannot be done by reading. RADD-770 shipped a gate that was
 *      PRESENT and wrong — it read an atom every active user held
 *      unconditionally, so it passed review and behaved like no gate at all. So
 *      the check here is not "is there a check?" but "does the DOM's claim match
 *      the actor's real permission set?": every `[data-needs]` element declares
 *      the atom it requires (the `useCan` seam emits it), and this compares
 *      `enabled` against `/auth/me` + each project's permissions.
 *
 * The account is seeded by the proof, so it does not depend on the dev database
 * happening to contain a suitable user, and it is REMOVED afterwards.
 *
 * The ROLE is a parameter (RADD-778). The default, the builtin Member, holds
 * almost every item atom, so over it the enabled-control check has little to
 * catch; the builtin **viewer** (item.read + page.read, nothing else) is the
 * persona every write affordance must refuse, and is the run that bites.
 *
 * Besides asserting, the run prints `unclaimed`: every ENABLED control on each
 * stop that declares no atom at all. That list is not a failure — a Star
 * button needs no permission — it is the sweep's work list, produced by the
 * app rather than written by hand.
 *
 * Usage: node scripts/restricted-access-proof.mjs <baseUrl> <adminEmail> <adminPassword> [member|viewer]
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword, roleKey = "member"] = process.argv.slice(2);
const PORT = 9475;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-restricted-proof");

const ACCOUNT = {
  email: "restricted-proof@example.test",
  name: "Restricted Proof",
  password: "restricted-proof-1",
};

/** Records every request the SPA makes, with a stack for the refusals. */
const RECORDER = `(() => {
  if (window.__denied) return true;
  window.__denied = [];
  const orig = window.fetch;
  window.fetch = async (...a) => {
    const where = new Error().stack || "";
    const r = await orig(...a);
    if (r.status === 403) {
      window.__denied.push({
        url: (r.url || String(a[0])).split("?")[0],
        // The caller matters more than the path: a plugin remote and the host
        // hit the same endpoint and only one of them is yours to fix.
        via: where.split("\\n").slice(1, 6).join(" | "),
      });
    }
    return r;
  };
  return true;
})()`;

/**
 * Every enabled control that declares NO atom — the work list. A control
 * counts as claimed when it or an ancestor carries `data-needs` (a menu
 * trigger wrapped by its gate is claimed). Hidden elements are skipped: a
 * control the actor cannot see is not a control that lies to them.
 */
const UNCLAIMED = `(() => {
  const sel = "button, input:not([type=hidden]), textarea, select, [contenteditable=true], [role=menuitem]";
  return [...document.querySelectorAll(sel)]
    .filter((el) => !el.closest("[data-needs]"))
    .filter((el) => !el.matches(":disabled") && el.getAttribute("aria-disabled") !== "true")
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
    .map((el) => (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || el.getAttribute("title") || el.tagName).trim().replace(/\\s+/g, " ").slice(0, 40));
})()`;

/**
 * Every control that declares an atom, and whether it is enabled.
 *
 * `disabled` is read off the element AND its computed pointer-events, because a
 * control can be inert in two different ways and only one of them is an
 * attribute.
 */
const CLAIMS = `(() => {
  return [...document.querySelectorAll("[data-needs]")].map((el) => ({
    needs: el.getAttribute("data-needs"),
    project: el.getAttribute("data-needs-project") || null,
    anyProject: el.getAttribute("data-needs-scope") === "any",
    // ":disabled", not ".disabled": the property ignores an ancestor
    // fieldset[disabled] (the issue rail gate); the pseudo-class does not.
    enabled: !el.matches(":disabled") && getComputedStyle(el).pointerEvents !== "none",
    label: (el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 40),
  }));
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1000);
  await session.login(baseUrl, adminEmail, adminPassword);

  // Seed the account as the admin, then hand the browser over to it.
  const seeded = await session.eval(`(async () => {
    const existing = await (await fetch("/api/v1/users?q=${ACCOUNT.email}", {credentials:"include"})).json();
    let user = Array.isArray(existing) ? existing[0] : null;
    if (!user) {
      user = await (await fetch("/api/v1/users", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(${JSON.stringify({ ...ACCOUNT, instance_role: "member" })}),
      })).json();
    }
    // Give it the builtin role under test (Member by default) on ONE project, scoped.
    //
    // Not a bare account: a member with no project role never renders the
    // editors at all, so a walk finds nothing and passes vacuously — the exact
    // trap RADD-769's first verification fell into. A project member with the
    // ordinary role renders nearly every surface while still lacking
    // project.manage, item.delete and every admin atom, which is what makes the
    // enabled-control check bite.
    const roles = await (await fetch("/api/v1/roles", {credentials:"include"})).json();
    const grantedRole = roles.find((r) => r.key === ${JSON.stringify(roleKey)});
    const projects = await (await fetch("/api/v1/projects", {credentials:"include"})).json();
    const project = projects[0];
    if (grantedRole && project) {
      await fetch("/api/v1/role-grants", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ role_id: grantedRole.id, user_id: user.id, project_ids: [project.id] }),
      });
    }
    return { id: user.id, projectKey: project ? project.key : null };
  })()`);

  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  const loginStatus = await session.login(baseUrl, ACCOUNT.email, ACCOUNT.password);

  // What this actor may actually do — from the server, never a hand-written list.
  const actor = await session.eval(`(async () => {
    const me = await (await fetch("/api/v1/auth/me", {credentials:"include"})).json();
    let projects = [];
    try {
      const res = await fetch("/api/v1/projects", {credentials:"include"});
      if (res.ok) projects = await res.json();
    } catch { /* a member entitled to none is a valid state */ }
    return {
      global: me.permissions || [],
      byProject: Object.fromEntries((projects || []).map((p) => [p.id, p.permissions || []])),
      firstProject: projects[0] ? { id: projects[0].id, key: projects[0].key } : null,
    };
  })()`);

  const stops = [];
  const claims = [];
  async function visit(label, path, settle = 3500) {
    await session.navigate(baseUrl + path, 400);
    await session.eval(RECORDER);
    await sleep(settle);
    const denied = await session.eval(`(window.__denied || [])`);
    const seen = await session.eval(CLAIMS);
    const unclaimed = await session.eval(UNCLAIMED);
    stops.push({ label, path, denied, controls: seen.length, unclaimed });
    for (const claim of seen) claims.push({ ...claim, at: label });
  }

  // A member's ordinary day: the home surface, an issue, a page, a view, the
  // timesheet. Settings is deliberately included — it is where most of the
  // un-gated writes live.
  const target = await session.eval(`(async () => {
    const items = await (await fetch("/api/v1/items?limit=1", {credentials:"include"})).json();
    const rows = Array.isArray(items) ? items : (items.items || items.results || []);
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = Array.isArray(spaces) && spaces[0] ? spaces[0] : null;
    let page = null;
    if (space) {
      const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
      page = Array.isArray(pages) ? pages[0] : null;
    }
    let boardView = null;
    try {
      const views = await (await fetch("/api/v1/views", {credentials:"include"})).json();
      if (Array.isArray(views) && views[0]) boardView = "/views/" + views[0].id;
    } catch { /* no views visible is fine */ }
    return {
      key: rows[0] ? rows[0].key : null,
      space: space ? space.slug : null,
      page: page ? page.slug : null,
      boardView,
    };
  })()`);

  await visit("my work", "/");
  if (target.key) await visit("issue", "/issues/" + target.key, 4500);
  if (target.boardView) await visit("board", target.boardView, 4000);
  if (target.space && target.page) await visit("page", `/pages/${target.space}/${target.page}`, 4000);
  if (target.space) await visit("page space", `/pages/${target.space}`);
  await visit("timesheet", "/timesheet");
  await visit("projects", "/projects");
  await visit("settings profile", "/settings/profile");

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // Clean up before asserting, so a failure never leaves the account behind.
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  const removed = await session.eval(`(async () => {
    const res = await fetch("/api/v1/users/${seeded.id}", { method: "DELETE", credentials: "include" });
    return res.status;
  })()`);

  // A control lies when it is enabled and the actor does not hold its atom.
  const holds = (claim) => {
    // A cross-project question (`useCan` with `anyProject`) is answered by the
    // global set OR any project's — the same union the SPA resolves.
    if (claim.anyProject) {
      return [actor.global, ...Object.values(actor.byProject)].some((set) => set.includes(claim.needs));
    }
    const set = claim.project ? actor.byProject[claim.project] || [] : actor.global;
    return set.includes(claim.needs);
  };
  const liars = claims.filter((c) => c.enabled && !holds(c));
  const overGated = claims.filter((c) => !c.enabled && holds(c));
  const denied = stops.flatMap((s) => s.denied.map((d) => ({ ...d, at: s.label })));

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the restricted account signed in": loginStatus === 204,
    // Restricted in the way that matters: no manage tier anywhere. If this ever
    // passes because the actor is secretly powerful, every check below is noise.
    "and is genuinely restricted":
      actor.global.length > 0 &&
      !actor.global.includes("global.manage") &&
      !Object.values(actor.byProject).some((set) => set.includes("project.manage")),
    "it walked every surface": stops.length >= 5,
    // The headline: enforcement never has to speak to this person.
    "no permission refusal reached the person": denied.length === 0,
    // The half that cannot be reviewed: the DOM's claims match reality.
    "every enabled control is one the actor may use": liars.length === 0,
    "and nothing is disabled that they could have used": overGated.length === 0,
    // A run that annotated nothing would pass the two above vacuously.
    "controls actually declared their permissions": claims.length > 0,
    "no console errors": consoleErrors.length === 0,
    "the seeded account was removed": removed === 204,
  };

  return report(checks, {
    actor: { global: actor.global, projects: Object.keys(actor.byProject).length },
    role: roleKey,
    stops: stops.map((s) => ({ ...s, denied: s.denied.length })),
    deniedDetail: denied.slice(0, 10),
    claimCount: claims.length,
    liars: liars.slice(0, 20),
    overGated: overGated.slice(0, 10),
    consoleErrors: consoleErrors.slice(0, 5),
  });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
