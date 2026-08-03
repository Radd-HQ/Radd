/**
 * Proves RADD-791/793 in a browser: a wiki space is a scope, and there is a
 * screen for it.
 *
 * The server-side rules live in `tests/test_space_scope.py`. What cannot be
 * asserted from a test client is the half that decides whether the feature
 * exists for a person: does the wiki nav show the granted space and hide the
 * other, and does Settings → Pages actually let an admin hand access out?
 *
 * Spec 87's lesson is the reason this is a proof rather than a screenshot: all
 * 47 global atoms were ungrantable for a year because nothing could deliver
 * them. A scope with no screen is the same failure.
 *
 * Restores the Baseline and removes what it created, INCLUDING after a failure.
 *
 * Usage: node scripts/space-access-proof.mjs <baseUrl> <adminEmail> <adminPassword>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
const PORT = 9483;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-space-access-proof");

const ACCOUNT = {
  email: "space-access-proof@example.test",
  name: "Space Access Proof",
  password: "space-access-1",
};
const STAMP = Math.abs(
  [...ACCOUNT.email].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7),
).toString(36);

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1000);
  await session.login(baseUrl, adminEmail, adminPassword);

  const seeded = await session.eval(`(async () => {
    const j = (r) => r.json();
    const post = (u, b) => fetch(u, {method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});

    const roles = await j(await fetch("/api/v1/roles", {credentials:"include"}));
    const baseline = roles.find((r) => r.key === "baseline");
    const previousBaseline = baseline.permissions;
    await fetch("/api/v1/roles/" + baseline.id, {method:"PATCH",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({permissions: []})});

    // Two spaces: one granted, one withheld. A single space cannot show a
    // boundary — it would pass just as well if the scope did nothing.
    const granted = await j(await post("/api/v1/page-spaces",
      {name: "Granted ${STAMP}", slug: "granted-${STAMP}"}));
    const withheld = await j(await post("/api/v1/page-spaces",
      {name: "Withheld ${STAMP}", slug: "withheld-${STAMP}"}));
    await post("/api/v1/pages", {space_id: granted.id, title: "Readable page", body: "hello"});
    await post("/api/v1/pages", {space_id: withheld.id, title: "Secret page", body: "shh"});

    let role = roles.find((r) => r.key === "space-proof-reader");
    if (!role) {
      role = await j(await post("/api/v1/roles", {
        key: "space-proof-reader", name: "Space Proof Reader",
        permissions: ["page.read", "comment.write", "item.read"],
      }));
    }
    const existing = await j(await fetch("/api/v1/users?q=${ACCOUNT.email}", {credentials:"include"}));
    let user = Array.isArray(existing) ? existing[0] : null;
    if (!user) user = await j(await post("/api/v1/users",
      ${JSON.stringify({ ...ACCOUNT, instance_role: "member" })}));

    // THE grant under test: a role, scoped to ONE space.
    const grantRes = await post("/api/v1/role-grants",
      {role_id: role.id, user_id: user.id, space_ids: [granted.id]});
    return {
      userId: user.id, roleId: role.id, baselineId: baseline.id, previousBaseline,
      grantedId: granted.id, grantedSlug: granted.slug, grantedName: granted.name,
      withheldId: withheld.id, withheldSlug: withheld.slug,
      grantStatus: grantRes.status,
    };
  })()`);

  // --- the ADMIN half: does the screen exist and show the grant? -------------
  await session.navigate(baseUrl + "/settings/pages", 600);
  await sleep(3000);
  const adminView = await session.eval(`(async () => {
    const button = [...document.querySelectorAll("button")]
      .find((b) => (b.getAttribute("aria-label") || "").startsWith("Access for ${'Granted ' + STAMP}"));
    if (!button) return { panelButton: false };
    button.click();
    await new Promise((r) => setTimeout(r, 1200));
    const panel = button.closest("li");
    const text = (panel?.textContent || "").replace(/\\s+/g, " ");
    return {
      panelButton: true,
      // The seeded grant, named in the panel — not just "a panel rendered".
      listsTheGrant: text.includes("Space Proof Reader"),
      hasGrantAction: [...(panel?.querySelectorAll("button") || [])]
        .some((b) => (b.textContent || "").includes("Grant role")),
    };
  })()`);

  // --- the MEMBER half: does the scope actually shape the wiki? --------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  const loginStatus = await session.login(baseUrl, ACCOUNT.email, ACCOUNT.password);

  const api = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const pages = await fetch("/api/v1/page-spaces/${seeded.withheldId}/pages", {credentials:"include"});
    const search = await (await fetch("/api/v1/pages/search?q=Secret", {credentials:"include"})).json();
    return {
      spaceSlugs: (spaces || []).map((s) => s.slug),
      withheldPagesStatus: pages.status,
      searchHitsSecret: ((search.results) || []).some((r) => /Secret/.test(r.title)),
    };
  })()`);

  await session.navigate(baseUrl + "/pages", 600);
  await sleep(3000);
  const wiki = await session.eval(`(() => {
    const text = document.body.textContent || "";
    return {
      showsGranted: text.includes("Granted ${STAMP}"),
      showsWithheld: text.includes("Withheld ${STAMP}"),
    };
  })()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // --- restore BEFORE asserting --------------------------------------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  const restored = await session.eval(`(async () => {
    const del = (u) => fetch(u, {method:"DELETE", credentials:"include"});
    const patch = await fetch("/api/v1/roles/${seeded.baselineId}", {
      method:"PATCH", credentials:"include", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({permissions: ${JSON.stringify(seeded.previousBaseline)}})});
    const userDel = await del("/api/v1/users/${seeded.userId}");
    await del("/api/v1/page-spaces/${seeded.grantedId}?force=true");
    await del("/api/v1/page-spaces/${seeded.withheldId}?force=true");
    await del("/api/v1/roles/${seeded.roleId}");
    const after = await (await fetch("/api/v1/roles", {credentials:"include"})).json();
    return {
      patch: patch.status, userDel: userDel.status,
      baseline: (after.find((r) => r.key === "baseline") || {}).permissions,
    };
  })()`);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the space-scoped grant was accepted": seeded.grantStatus === 201,
    "the scoped account signed in": loginStatus === 204,
    // RADD-793: the screen exists, and shows the real grant rather than chrome.
    "Settings → Pages offers an Access panel per space": adminView.panelButton === true,
    "the panel lists the space's grant": adminView.listsTheGrant === true,
    "the panel offers a way to grant": adminView.hasGrantAction === true,
    // RADD-791: the scope shapes what the member sees.
    "the API lists only the granted space":
      JSON.stringify(api.spaceSlugs) === JSON.stringify([seeded.grantedSlug]),
    "the withheld space's pages are refused": api.withheldPagesStatus === 403,
    "search does not surface the withheld space's page": api.searchHitsSecret === false,
    "the wiki shows the granted space": wiki.showsGranted === true,
    "and does not show the withheld one": wiki.showsWithheld === false,
    "no console errors": consoleErrors.length === 0,
    "the Baseline was restored":
      restored.patch === 200 &&
      JSON.stringify(restored.baseline) === JSON.stringify(seeded.previousBaseline),
    "the seeded account was removed": restored.userDel === 204,
  };

  return report(checks, { seeded: { grantStatus: seeded.grantStatus }, adminView, api, wiki, restored,
    consoleErrors: consoleErrors.slice(0, 5) });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
