/**
 * Proves RADD-788 against the exact live scenario that produced it.
 *
 * An admin empties the Baseline role (RADD-773's setting), and a person's ENTIRE
 * access is one role grant SCOPED to a project — which is the normal shape of a
 * grant, and which contributes nothing at global scope. Before the fix that
 * account could reach Reports and nothing else: `GET /views` refused on a global
 * `item.read` check, and since specs 61-67 deleted the builtin board/list/planning
 * pages, a refused view list leaves a project containing nothing.
 *
 * The server-side regression lives in `tests/test_scoped_member.py`. This is the
 * half that cannot be asserted from a test client: whether the person actually
 * SEES a board. A 200 on /views proves the endpoint answered, not that the
 * sidebar rendered a link, that clicking it drew columns, or that the columns
 * hold cards. Each of those has been the bug at some point in this codebase.
 *
 * Restores the Baseline and removes the account on the way out, INCLUDING after
 * a failure — a permanently empty floor on the dev database would silently
 * change every later permission result.
 *
 * Usage: node scripts/scoped-member-proof.mjs <baseUrl> <adminEmail> <adminPassword>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
const PORT = 9477;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-scoped-member-proof");

const ACCOUNT = {
  email: "scoped-member-proof@example.test",
  name: "Scoped Member Proof",
  password: "scoped-member-1",
};

/** What "Studio Members" holds on the live instance. */
const ROLE_ATOMS = ["item.read", "item.create", "comment.write", "page.read", "view.create"];

const RECORDER = `(() => {
  if (window.__denied) return true;
  window.__denied = [];
  const orig = window.fetch;
  window.fetch = async (...a) => {
    const r = await orig(...a);
    if (r.status === 403) window.__denied.push((r.url || String(a[0])).split("?")[0]);
    return r;
  };
  return true;
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1000);
  await session.login(baseUrl, adminEmail, adminPassword);

  // --- set the live scenario up, as the admin -------------------------------
  const seeded = await session.eval(`(async () => {
    const j = (r) => r.json();
    const post = (url, body) => fetch(url, {
      method: "POST", credentials: "include",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });

    const roles = await j(await fetch("/api/v1/roles", {credentials:"include"}));
    const baseline = roles.find((r) => r.key === "baseline");
    const previousBaseline = baseline ? baseline.permissions : null;
    // The setting the admin actually used.
    await fetch("/api/v1/roles/" + baseline.id, {
      method: "PATCH", credentials: "include",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ permissions: [] }),
    });

    let scoped = roles.find((r) => r.key === "scoped-member-proof");
    if (!scoped) {
      scoped = await j(await post("/api/v1/roles", {
        key: "scoped-member-proof", name: "Scoped Member Proof",
        permissions: ${JSON.stringify(ROLE_ATOMS)},
      }));
    }

    const existing = await j(await fetch("/api/v1/users?q=${ACCOUNT.email}", {credentials:"include"}));
    let user = Array.isArray(existing) ? existing[0] : null;
    if (!user) {
      user = await j(await post("/api/v1/users", ${JSON.stringify({ ...ACCOUNT, instance_role: "member" })}));
    }

    // A project that HAS views and items, so an empty board cannot pass for a
    // working one. Picking blindly is how a proof reports success on a project
    // nobody has ever put an issue in.
    const projects = await j(await fetch("/api/v1/projects", {credentials:"include"}));
    let project = null;
    for (const p of projects) {
      const views = await j(await fetch("/api/v1/views?project_id=" + p.id, {credentials:"include"}));
      const items = await j(await fetch("/api/v1/items?project_id=" + p.id + "&limit=1", {credentials:"include"}));
      const rows = Array.isArray(items) ? items : (items.items || []);
      if (views.length && rows.length) { project = p; break; }
    }
    if (project) {
      await post("/api/v1/role-grants", {
        role_id: scoped.id, user_id: user.id, project_ids: [project.id],
      });
    }
    return {
      userId: user.id, roleId: scoped.id, baselineId: baseline.id,
      previousBaseline,
      projectId: project ? project.id : null, projectKey: project ? project.key : null,
    };
  })()`);

  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  const loginStatus = await session.login(baseUrl, ACCOUNT.email, ACCOUNT.password);

  // The actor, from the server — never a hand-written list.
  const actor = await session.eval(`(async () => {
    const me = await (await fetch("/api/v1/auth/me", {credentials:"include"})).json();
    const projects = await (await fetch("/api/v1/projects", {credentials:"include"})).json();
    return {
      global: me.permissions || [],
      projects: (projects || []).map((p) => ({ key: p.key, permissions: p.permissions })),
    };
  })()`);

  const stops = [];
  async function visit(label, path, settle = 3500) {
    await session.navigate(baseUrl + path, 500);
    await session.eval(RECORDER);
    await sleep(settle);
    stops.push({ label, path, denied: await session.eval(`(window.__denied || [])`) });
  }

  await visit("my work", "/");

  // Which board to open. A view route is `/v/$viewId`, or `/p/$key/v/$viewId`
  // when the view belongs to a project — the segment is `/p/`, not `/projects/`,
  // and neither `/views/$id` nor `/projects/$key/v/$id` exists. Both wrong
  // guesses render a BLANK page rather than a 404, so this proof reported a
  // working board as broken twice before the path was checked against a
  // privileged run. A UI proof needs its own control.
  const boardTarget = await session.eval(`(async () => {
    const views = await (await fetch("/api/v1/views?project_id=${seeded.projectId}", {credentials:"include"})).json();
    if (!Array.isArray(views) || !views.length) return { apiViewCount: 0, path: null };
    const view = views.find((v) => v.view_type === "board") || views[0];
    return {
      apiViewCount: views.length,
      path: view.project_id ? "/p/${seeded.projectKey}/v/" + view.id : "/v/" + view.id,
    };
  })()`);

  // The board itself, plus the sidebar AS SEEN FROM IT — the project tree
  // defaults collapsed and auto-expands for the current route, so probing the
  // links from the landing page would measure the fold, not the permission.
  let board = { cards: 0, sidebarViewLinks: 0 };
  if (boardTarget.path) {
    await visit("board", boardTarget.path, 5000);
    board = await session.eval(`(() => ({
      cards: document.querySelectorAll('a[href^="/issues/"]').length,
      sidebarViewLinks: document.querySelectorAll('aside a[href*="/v/"]').length,
    }))()`);
  }

  await visit("project reports", "/p/" + seeded.projectKey + "/reports", 4000);
  await visit("cross-project reports", "/reports", 4000);
  await visit("settings", "/settings");
  const settingsLanding = await session.eval(`location.pathname`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // --- restore BEFORE asserting, so a failure never leaves the floor empty ---
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  const restored = await session.eval(`(async () => {
    const r = await fetch("/api/v1/roles/${seeded.baselineId}", {
      method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ permissions: ${JSON.stringify(seeded.previousBaseline)} }),
    });
    const del = await fetch("/api/v1/users/${seeded.userId}", { method: "DELETE", credentials: "include" });
    await fetch("/api/v1/roles/${seeded.roleId}", { method: "DELETE", credentials: "include" });
    const after = await (await fetch("/api/v1/roles", {credentials:"include"})).json();
    const baseline = after.find((x) => x.key === "baseline");
    return { patch: r.status, userDelete: del.status, baseline: baseline ? baseline.permissions : null };
  })()`);

  const denied = stops.flatMap((s) => s.denied.map((url) => ({ url, at: s.label })));
  const projectPerms = actor.projects[0] ? actor.projects[0].permissions : [];

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the scoped account signed in": loginStatus === 204,
    // The scenario is genuinely the live one, or everything below is noise.
    "the Baseline really was empty and the grant really was project-scoped":
      actor.global.length === 0 && projectPerms.includes("item.read"),
    "the project is visible": actor.projects.length === 1,
    // The headline: a board exists, is linked, and has cards in it.
    "the view list is not empty": boardTarget.apiViewCount > 0,
    "the sidebar links to at least one view": board.sidebarViewLinks > 0,
    "the board drew cards": board.cards > 0,
    "no permission refusal reached the person": denied.length === 0,
    // RADD-788's second half: /settings used to land on Fields, which needs
    // field.manage, so the first click into Settings was a permission toast.
    "settings landed on a page this person can open": settingsLanding === "/settings/profile",
    "no console errors": consoleErrors.length === 0,
    // Cleanup is a CHECK, not a side effect: a permanently empty Baseline on the
    // dev database would quietly change every later permission result.
    "the Baseline was restored":
      restored.patch === 200 &&
      JSON.stringify(restored.baseline) === JSON.stringify(seeded.previousBaseline),
    "the seeded account was removed": restored.userDelete === 204,
  };

  return report(checks, {
    actor: { global: actor.global, project: actor.projects[0] || null },
    boardTarget,
    board,
    settingsLanding,
    denied: denied.slice(0, 10),
    restored,
    consoleErrors: consoleErrors.slice(0, 5),
  });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
