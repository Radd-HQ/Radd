/**
 * Spec 121 — the public-project walk, in a real browser (RADD-1146).
 *
 * As the admin: a PUBLIC project with contributions on, holding a public, an
 * internal and a restricted issue (the public one carrying a public and an
 * internal comment), a PRIVATE project, and a fresh account. Then:
 *
 *   anonymous  — the shell renders (Sign in in the avatar slot), /auth/me says
 *                anonymous, the list/comments show exactly the public rows,
 *                a hidden issue bounces to /login?next=…, and nothing on the
 *                public page 401s (no bell, no pins, no leave poll);
 *   signed in  — a fresh account comments on the public issue, files an
 *                issue in the public project, and is refused in the private one.
 *
 * Fixtures are purged at START (a run that died mid-seed must not poison the
 * next), and every probe was first validated against the admin.
 *
 *   node web/scripts/public-project-proof.mjs http://localhost:8000 admin@example.com change-me
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: public-project-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9477;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-public-project-proof");
const PUBLIC_KEY = "PUBPRF";
const PRIVATE_KEY = "PRVPRF";
const VISITOR = { email: "public-proof-visitor@example.test", name: "Public Proof Visitor", password: "public-proof-1" };

/** JSON helper that runs IN the page (cookies ride along). */
const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, credentials: "include",
      headers: body ? {"Content-Type": "application/json"} : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null; try { data = await r.json(); } catch {}
    return { status: r.status, data };
  };
`;

/** 401s the page made since load — resource timing carries the status. */
const UNAUTHORIZED = `(() => performance.getEntriesByType("resource")
  .filter((e) => e.responseStatus === 401).map((e) => e.name.replace(location.origin, "")))()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = {};
  try {
    await session.navigate(baseUrl + "/login", 800);
    const adminLogin = await session.login(baseUrl, adminEmail, adminPassword);
    checks["admin signs in"] = adminLogin === 204;

    // --- purge + seed, as the admin ---------------------------------------
    const seeded = await session.eval(`(async () => { ${API}
      // Projects have no delete route; a stale fixture project is REUSED after
      // its items are hard-deleted (spec 38) and its switches reset.
      const projects = (await api("GET", "/projects?limit=200")).data || [];
      const reuse = async (key, name) => {
        const stale = projects.find((p) => p.key === key);
        if (!stale) return (await api("POST", "/projects", { key, name })).data;
        const items = (await api("GET", "/items?project_id=" + stale.id + "&limit=200")).data || [];
        for (const item of items) await api("DELETE", "/items/" + item.id);
        await api("PUT", "/projects/" + stale.id + "/public-access", { public: false, contributions: false });
        return stale;
      };
      const me = (await api("GET", "/auth/me")).data;
      const users = (await api("GET", "/users?q=" + encodeURIComponent(${JSON.stringify(VISITOR.email)}))).data;
      const staleUser = Array.isArray(users) ? users.find((u) => u.email === ${JSON.stringify(VISITOR.email)}) : null;
      if (staleUser) await api("DELETE", "/users/" + staleUser.id + "?reassign_to=" + me.id);

      const pub = await reuse(${JSON.stringify(PUBLIC_KEY)}, "Public proof");
      const prv = await reuse(${JSON.stringify(PRIVATE_KEY)}, "Private proof");
      const access = await api("PUT", "/projects/" + pub.id + "/public-access", { public: true, contributions: true });
      const items = {};
      for (const visibility of ["public", "internal", "restricted"]) {
        items[visibility] = (await api("POST", "/items", { project_id: pub.id, title: visibility + " issue", visibility })).data;
      }
      const c1 = await api("POST", "/items/" + items.public.id + "/comments", { body: "a public comment", visibility: "public" });
      const c2 = await api("POST", "/items/" + items.public.id + "/comments", { body: "an internal note", visibility: "internal" });
      const visitor = (await api("POST", "/users", ${JSON.stringify({ ...VISITOR, instance_role: "member" })})).data;
      return { pub, prv, access: access.data, items, comments: [c1.status, c2.status], visitor };
    })()`);
    context.seeded = {
      pub: seeded.pub?.key, prv: seeded.prv?.key, public: seeded.access?.public,
      contributions: seeded.access?.contributions, items: Object.fromEntries(Object.entries(seeded.items).map(([k, v]) => [k, v?.key])),
      comments: seeded.comments, visitor: seeded.visitor?.id,
    };
    checks["project made public with contributions"] = seeded.access?.public === true && seeded.access?.contributions === true;
    checks["three issues + two comments seeded"] = Object.values(seeded.items).every((i) => i?.id) && seeded.comments.every((s) => s === 201);
    const pubId = seeded.pub.id;
    const publicKey = seeded.items.public.key;
    const internalKey = seeded.items.internal.key;

    // Admin control: every probe below is first shown to WORK for the admin.
    const adminView = await session.eval(`(async () => { ${API}
      const list = (await api("GET", "/items?project_id=${pubId}")).data;
      const comments = (await api("GET", "/items/${seeded.items.public.id}/comments")).data;
      return { keys: list.map((i) => i.key).sort(), comments: comments.map((c) => c.visibility).sort() };
    })()`);
    checks["admin control: sees all three issues"] = adminView.keys.length === 3;
    checks["admin control: sees both comments"] = adminView.comments.join(",") === "internal,public";

    await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);

    // --- the world -------------------------------------------------------
    await session.navigate(baseUrl + "/p/" + PUBLIC_KEY, 4000);
    const shell = await session.eval(`(async () => { ${API}
      const me = (await api("GET", "/auth/me")).data;
      const signIn = [...document.querySelectorAll('a[href^="/login"]')].find((a) => /sign in/i.test(a.textContent || ""));
      const bell = document.querySelector('[aria-label^="Inbox"]');
      const list = (await api("GET", "/items?project_id=${pubId}")).data;
      const comments = (await api("GET", "/items/${seeded.items.public.id}/comments")).data;
      const project = await api("GET", "/projects/${pubId}");
      const privateProject = await api("GET", "/projects/${seeded.prv.id}");
      return {
        path: location.pathname, anonymous: me && me.anonymous === true,
        signIn: Boolean(signIn), signInNext: signIn ? signIn.getAttribute("href") : null, bell: Boolean(bell),
        keys: Array.isArray(list) ? list.map((i) => i.key) : list,
        comments: Array.isArray(comments) ? comments.map((c) => c.visibility) : comments,
        projectPublic: project.data && project.data.public, privateStatus: privateProject.status,
        unauthorized: ${UNAUTHORIZED},
      };
    })()`);
    context.anonymous = shell;
    checks["anonymous: stays on the project page (no login bounce)"] = shell.path.startsWith("/p/" + PUBLIC_KEY);
    checks["anonymous: /auth/me says anonymous"] = shell.anonymous === true;
    checks["anonymous: Sign in offered, carrying the page"] = shell.signIn && String(shell.signInNext).includes("next=");
    checks["anonymous: no inbox bell"] = shell.bell === false;
    checks["anonymous: list shows exactly the public issue"] = Array.isArray(shell.keys) && shell.keys.join(",") === publicKey;
    checks["anonymous: comments show the public one only"] = Array.isArray(shell.comments) && shell.comments.join(",") === "public";
    checks["anonymous: project payload says public"] = shell.projectPublic === true;
    checks["anonymous: the private project is not there"] = shell.privateStatus === 403 || shell.privateStatus === 404;
    checks["anonymous: the public page makes no 401 request"] = Array.isArray(shell.unauthorized) && shell.unauthorized.length === 0;

    await session.navigate(baseUrl + "/issues/" + publicKey, 4000);
    // The title is an editable input (not in innerText); the key is plain text.
    const issuePage = await session.eval(`({ path: location.pathname, title: document.title, body: document.body.innerText.includes(${JSON.stringify(publicKey)}), unauthorized: ${UNAUTHORIZED} })`);
    context.issuePage = issuePage;
    checks["anonymous: the public issue renders"] = issuePage.path === "/issues/" + publicKey && issuePage.body === true;
    // The rail's widgets (watchers, SLA, pickers, plugin cards) ask once and
    // take the refusal quietly; what must never happen is a 401 in a LOOP.
    const repeated = issuePage.unauthorized.filter((url, i, all) => all.indexOf(url) !== i);
    context.issuePage.repeated = repeated;
    checks["anonymous: the issue page never 401s in a loop"] = repeated.length === 0;

    await session.navigate(baseUrl + "/issues/" + internalKey, 4000);
    const bounced = await session.eval(`({ path: location.pathname, search: location.search })`);
    context.bounced = bounced;
    checks["anonymous: a hidden issue bounces to sign-in with next"] =
      bounced.path === "/login" && decodeURIComponent(bounced.search).includes("/issues/" + internalKey);

    // --- a fresh account -------------------------------------------------
    const visitorLogin = await session.login(baseUrl, VISITOR.email, VISITOR.password);
    checks["visitor signs in"] = visitorLogin === 204;
    const contributes = await session.eval(`(async () => { ${API}
      const comment = await api("POST", "/items/${seeded.items.public.id}/comments", { body: "hello from outside", visibility: "public" });
      const filed = await api("POST", "/items", { project_id: "${pubId}", title: "filed from outside" });
      const refused = await api("POST", "/items", { project_id: "${seeded.prv.id}", title: "not here" });
      const internalNote = await api("POST", "/items/${seeded.items.public.id}/comments", { body: "sneaky", visibility: "internal" });
      const hidden = await api("GET", "/items/${seeded.items.internal.id}");
      return { comment: comment.status, filed: filed.status, filedKey: filed.data && filed.data.key, refused: refused.status, internalNote: internalNote.status, hidden: hidden.status };
    })()`);
    context.visitor = contributes;
    checks["visitor: comments on the public issue"] = contributes.comment === 201;
    checks["visitor: files an issue in the public project"] = contributes.filed === 201;
    checks["visitor: refused in the private project"] = contributes.refused === 403;
    checks["visitor: cannot post an internal note"] = contributes.internalNote === 403;
    checks["visitor: cannot read the internal issue"] = contributes.hidden === 404 || contributes.hidden === 403;
    await session.navigate(baseUrl + "/issues/" + publicKey, 3500);
    await session.screenshot(resolve(process.env.TMPDIR || "/tmp", "public-project-proof.png"));

    const errors = session.consoleErrors.filter((e) => !/favicon|ResizeObserver/.test(e));
    context.consoleErrors = errors.slice(0, 8);
    checks["no console exceptions on the walk"] = !errors.some((e) => e.startsWith("EXCEPTION"));
  } finally {
    await close();
  }
  process.exit(report(checks, context) ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
