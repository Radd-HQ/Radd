/**
 * Proves RADD-835: every surface that names, counts, links to or notifies
 * about a row resolves through the same visibility seam.
 *
 * The scenario is the post-RADD-825 floor: an account holding `item.read@own`
 * and nothing else, in a project that also contains a hidden issue, a hidden
 * epic whose SUBTASK the account reported, and a dependency link from the
 * account's own issue to the hidden one. Every check reduces to one story:
 *
 *   - lists/boards: the rows themselves — only the two OWN rows;
 *   - counts vs rows: /items/count == the list's total == what the DOM shows
 *     (the "42 issues beside a list of 3" failure);
 *   - search (FTS + the palette's endpoint): a token planted in BOTH titles
 *     returns only the visible one, and the hidden TITLE never reaches the DOM;
 *   - links: the own issue's link section never names the hidden target;
 *   - breadcrumbs: the subtask renders without its hidden parent's title;
 *   - rollup: the hidden epic is OMITTED from the response, not zeroed;
 *   - notifications: a mention on the hidden row never reaches the inbox,
 *     while a mention on the own row does (send-time filtering, and the
 *     positive control that the pipeline runs at all);
 *   - nav: no Timesheet entry for an account that cannot use it (nav facts).
 *
 * Leak DETECTABILITY is proven, not assumed: the same probes run as ADMIN
 * first and must see the hidden row — a probe that cannot see the leak on an
 * unfiltered account would pass vacuously on the filtered one.
 *
 * Reuses a fixed project key (SWPF) and removes its items + the account on
 * exit, so repeated runs do not accumulate junk.
 *
 * Usage: node scripts/relation-sweep-proof.mjs <baseUrl> <adminEmail> <adminPassword>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
const PORT = 9495;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-relation-sweep-proof");

const RESTRICTED = {
  email: "sweep-proof@example.test",
  name: "Sweep Proof",
  password: "sweep-proof-1",
};
const RUN = Math.random().toString(36).slice(2, 8);
const TOKEN = `swptoken${RUN}`; // in BOTH titles — the search bait
const HIDDEN_MARK = `swphidden${RUN}`; // only in the hidden titles

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1000);
  await session.login(baseUrl, adminEmail, adminPassword);

  // --- seed (as admin) -------------------------------------------------------
  const seeded = await session.eval(`(async () => {
    const j = (r) => r.json();
    const post = (u, b) => fetch(u, {method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});

    const users = await j(await fetch("/api/v1/users?q=${RESTRICTED.email}", {credentials:"include"}));
    const restricted = (Array.isArray(users) && users[0])
      || await j(await post("/api/v1/users", {...${JSON.stringify(RESTRICTED)}, instance_role: "member"}));

    const projects = await j(await fetch("/api/v1/projects", {credentials:"include"}));
    const project = projects.find((p) => p.key === "SWPF")
      || await j(await post("/api/v1/projects", {key: "SWPF", name: "Relation Sweep Proof"}));

    // A prior run that died mid-seed leaves rows behind; a proof that is not
    // idempotent fails for reasons that have nothing to do with the code
    // under test (the requester-loop lesson). Purge before seeding.
    const stale = await j(await fetch("/api/v1/items?project_id=" + project.id, {credentials:"include"}));
    for (const row of (Array.isArray(stale) ? stale : (stale.items || []))) {
      await fetch("/api/v1/items/" + row.id, {method:"DELETE", credentials:"include"});
    }

    const mk = (b) => j(post("/api/v1/items", b).then((r) => r));
    const own = await j(await post("/api/v1/items", {project_id: project.id,
      title: "own issue ${TOKEN}", reporter_id: restricted.id}));
    const hidden = await j(await post("/api/v1/items", {project_id: project.id,
      title: "${HIDDEN_MARK} issue ${TOKEN}"}));
    const epic = await j(await post("/api/v1/items", {project_id: project.id,
      kind: "epic", title: "${HIDDEN_MARK} epic parent"}));
    const sub = await j(await post("/api/v1/items", {project_id: project.id,
      kind: "issue", parent_id: epic.id, title: "own child under hidden parent",
      reporter_id: restricted.id}));
    // A dependency from the OWN issue to the HIDDEN one.
    await post("/api/v1/items/" + own.id + "/links", {target_id: hidden.id, link_type: "blocks"});
    // Mentions: one on the hidden row (must never arrive), one on the own row
    // (the positive control that notify runs at all).
    await post("/api/v1/items/" + hidden.id + "/comments",
      {body: "heads up @[${RESTRICTED.name}](user:" + restricted.id + ") on the hidden row"});
    await post("/api/v1/items/" + own.id + "/comments",
      {body: "ping @[${RESTRICTED.name}](user:" + restricted.id + ") on your own row"});
    return {restrictedId: restricted.id, projectId: project.id,
            ownId: own.id, ownKey: own.key, hiddenId: hidden.id, hiddenKey: hidden.key,
            epicId: epic.id, epicKey: epic.key, subId: sub.id, subKey: sub.key};
  })()`);
  if (!seeded || !seeded.subId) {
    console.error("seed failed:", JSON.stringify(seeded));
    process.exit(1);
  }

  // Search indexes through the outbox consumer — wait until the OWN title is
  // findable as admin before asserting anything about filtering.
  let indexed = false;
  for (let i = 0; i < 30 && !indexed; i++) {
    await sleep(1000);
    const hits = await session.eval(`(async () => {
      const r = await fetch("/api/v1/search?q=${TOKEN}", {credentials:"include"});
      return (await r.json()).results?.length ?? 0;
    })()`);
    indexed = hits >= 2;
  }

  // --- leak detectability: the probes MUST see the hidden row as admin ------
  const adminView = await session.eval(`(async () => {
    const j = (r) => r.json();
    const list = await j(await fetch("/api/v1/items?project_id=${seeded.projectId}", {credentials:"include"}));
    const rows = Array.isArray(list) ? list : (list.items || []);
    const count = await j(await fetch("/api/v1/items/count?project_id=${seeded.projectId}", {credentials:"include"}));
    const search = await j(await fetch("/api/v1/search?q=${TOKEN}", {credentials:"include"}));
    const links = await j(await fetch("/api/v1/items/${seeded.ownId}", {credentials:"include"}));
    return {
      rowCount: rows.length,
      count: count.count ?? count.total ?? count,
      seesHidden: rows.some((r) => r.id === "${seeded.hiddenId}"),
      searchHits: (search.results || []).length,
      linkNamesHidden: JSON.stringify(links.links || {}).includes("${seeded.hiddenKey}"),
    };
  })()`);

  // --- the restricted account ------------------------------------------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, RESTRICTED.email, RESTRICTED.password);

  const api = await session.eval(`(async () => {
    const j = (r) => r.json();
    const me = await j(await fetch("/api/v1/auth/me", {credentials:"include"}));
    const list = await j(await fetch("/api/v1/items?project_id=${seeded.projectId}", {credentials:"include"}));
    const rows = Array.isArray(list) ? list : (list.items || []);
    const count = await j(await fetch("/api/v1/items/count?project_id=${seeded.projectId}", {credentials:"include"}));
    const all = await j(await fetch("/api/v1/items", {credentials:"include"}));
    const allRows = Array.isArray(all) ? all : (all.items || []);
    const search = await j(await fetch("/api/v1/search?q=${TOKEN}", {credentials:"include"}));
    const own = await j(await fetch("/api/v1/items/${seeded.ownId}", {credentials:"include"}));
    const hiddenDirect = await fetch("/api/v1/items/${seeded.hiddenId}", {credentials:"include"});
    const sub = await j(await fetch("/api/v1/items/${seeded.subId}", {credentials:"include"}));
    const rollup = await j(await fetch("/api/v1/items/rollup", {method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({item_ids: ["${seeded.epicId}"]})}));
    const notifications = await j(await fetch("/api/v1/notifications", {credentials:"include"}));
    const notifRows = notifications.notifications || notifications.items || notifications || [];
    const payload = JSON.stringify(notifRows);
    return {
      navTimesheet: me.nav ? me.nav.timesheet : null,
      rowKeys: rows.map((r) => r.key).sort(),
      count: count.count ?? count.total ?? count,
      allSeesHidden: allRows.some((r) => r.id === "${seeded.hiddenId}"),
      searchKeys: (search.results || []).map((r) => r.key ?? r.item_key ?? "").filter(Boolean),
      searchLeaksTitle: JSON.stringify(search).includes("${HIDDEN_MARK}"),
      ownLinksLeak: JSON.stringify(own.links || {}).includes("${seeded.hiddenKey}"),
      hiddenDirectStatus: hiddenDirect.status,
      subParentLeak: JSON.stringify(sub.parent || null).includes("${HIDDEN_MARK}"),
      rollupHasEpic: Object.keys(rollup || {}).includes("${seeded.epicId}"),
      notifMentionsOwn: payload.includes("${seeded.ownKey}"),
      notifMentionsHidden: payload.includes("${seeded.hiddenKey}"),
    };
  })()`);

  // --- the DOM tells the same story -----------------------------------------
  // Surfaces are VIEWS (specs 61-67): the project home lands on its seeded
  // Board/List view, which is the list surface a person actually sees.
  await session.navigate(`${baseUrl}/p/SWPF`, 3000);
  const listDom = await session.eval(`(() => {
    const text = document.body.innerText;
    return {
      showsOwn: text.includes("${seeded.ownKey}"),
      leaksHidden: text.includes("${HIDDEN_MARK}") || text.includes("${seeded.hiddenKey}"),
      hasTimesheetNav: !!document.querySelector('a[href*="/timesheet"]'),
    };
  })()`);
  await session.navigate(`${baseUrl}/issues/${seeded.subKey}`, 2500);
  const subDom = await session.eval(`(() => {
    const text = document.body.innerText;
    return { open: text.includes("${seeded.subKey}"), leaksParent: text.includes("${HIDDEN_MARK}") };
  })()`);
  await session.navigate(`${baseUrl}/issues/${seeded.ownKey}`, 2500);
  const ownDom = await session.eval(`(() => {
    const text = document.body.innerText;
    return { open: text.includes("${seeded.ownKey}"), leaksLink: text.includes("${seeded.hiddenKey}") };
  })()`);
  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // --- restore ---------------------------------------------------------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  await session.eval(`(async () => {
    const del = (u) => fetch(u, {method:"DELETE", credentials:"include"});
    for (const id of ["${seeded.subId}", "${seeded.epicId}", "${seeded.hiddenId}", "${seeded.ownId}"]) {
      await del("/api/v1/items/" + id);
    }
    const me = await (await fetch("/api/v1/auth/me", {credentials:"include"})).json();
    await del("/api/v1/users/${seeded.restrictedId}?reassign_to=" + me.id);
  })()`);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the search index caught up before filtering was judged": indexed === true,
    // Detectability: an unfiltered account sees everything these probes watch.
    "as admin the probes see the hidden row": adminView.seesHidden === true,
    "as admin the count covers it": adminView.count >= 4,
    "as admin search returns both baited titles": adminView.searchHits >= 2,
    "as admin the link names the hidden key": adminView.linkNamesHidden === true,
    // Rows: lists and the cross-project listing.
    "the project list is exactly the two own rows":
      JSON.stringify(api.rowKeys) === JSON.stringify([seeded.ownKey, seeded.subKey].sort()),
    "the cross-project listing hides the hidden row": api.allSeesHidden === false,
    // Counts vs rows — the failure that actually happens.
    "the count equals the visible rows": api.count === 2,
    // Search: FTS + the palette ride the same endpoint.
    "search returns only the visible bait": api.searchKeys.includes(seeded.ownKey)
      && !api.searchKeys.includes(seeded.hiddenKey),
    "no hidden title in the search payload": api.searchLeaksTitle === false,
    // Links, direct read, breadcrumb, rollup.
    "the own issue's links never name the hidden key": api.ownLinksLeak === false,
    "a direct read of the hidden row is 404, not 403": api.hiddenDirectStatus === 404,
    "the subtask's parent ref hides the epic title": api.subParentLeak === false,
    "the rollup omits the hidden epic": api.rollupHasEpic === false,
    // Notifications: send-time filtering with a live positive control.
    "the mention on the own row arrived": api.notifMentionsOwn === true,
    "the mention on the hidden row never did": api.notifMentionsHidden === false,
    // Nav facts.
    "the account's nav facts exclude the timesheet": api.navTimesheet === false,
    // The DOM agrees with the API on every leak probe.
    "the list DOM shows the own row and no hidden title":
      listDom.showsOwn === true && listDom.leaksHidden === false,
    "the sidebar offers no timesheet": listDom.hasTimesheetNav === false,
    "the child page renders without its hidden parent's title":
      subDom.open === true && subDom.leaksParent === false,
    "the own issue page renders without the hidden link target":
      ownDom.open === true && ownDom.leaksLink === false,
    "no console errors": consoleErrors.length === 0,
  };
  report(checks, { consoleErrors, adminView, api, listDom, subDom, ownDom });
}

main().then(
  () => process.exit(process.exitCode || 0),
  (error) => {
    console.error(error);
    process.exit(1);
  },
);
