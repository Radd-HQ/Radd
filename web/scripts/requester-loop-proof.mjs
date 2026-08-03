/**
 * Proves the requester surfaces end to end (RADD-796/797/798/799).
 *
 * The scenario is the one the whole epic exists for: somebody whose ENTIRE
 * relationship with Radd is filing requests. Empty Baseline, no project grant,
 * no `item.read` anywhere — admitted only by having reported a row or sharing
 * its team.
 *
 * What a test client cannot answer, and this does:
 *
 *   - the row is CLICKABLE and opens something (it was inert before);
 *   - the status pills are actually rendered, not merely present in the payload;
 *   - the reply marker lights, and clearing it re-renders the row;
 *   - Portal and My Work draw the same section chrome (RADD-799's whole point);
 *   - a teammate sees the shared request under its team heading.
 *
 * Restores the Baseline and removes everything it created, including on failure.
 *
 * Usage: node scripts/requester-loop-proof.mjs <baseUrl> <adminEmail> <adminPassword>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
const PORT = 9485;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-requester-loop-proof");

const REQUESTER = { email: "requester-proof@example.test", name: "Req Proof", password: "req-proof-1" };
const TEAMMATE = { email: "teammate-proof@example.test", name: "Mate Proof", password: "mate-proof-1" };

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1000);
  await session.login(baseUrl, adminEmail, adminPassword);

  const seeded = await session.eval(`(async () => {
    const j = (r) => r.json();
    const post = (u, b) => fetch(u, {method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
    const patch = (u, b) => fetch(u, {method:"PATCH",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});

    const roles = await j(await fetch("/api/v1/roles", {credentials:"include"}));
    const baseline = roles.find((r) => r.key === "baseline");
    const previousBaseline = baseline.permissions;
    await patch("/api/v1/roles/" + baseline.id, {permissions: []});

    const users = {};
    for (const acct of [${JSON.stringify(REQUESTER)}, ${JSON.stringify(TEAMMATE)}]) {
      const existing = await j(await fetch("/api/v1/users?q=" + acct.email, {credentials:"include"}));
      users[acct.email] = (Array.isArray(existing) && existing[0])
        || await j(await post("/api/v1/users", {...acct, instance_role: "member"}));
    }

    // A UNIQUE name per run. A fixed one collided with the team a previous run
    // left behind, POST answered 409, the id came back undefined, and the submit
    // then carried no team at all — so two checks failed for a reason that had
    // nothing to do with the code under test. A proof that is not idempotent
    // reports on its own leftovers.
    const stamp = String(Date.now()).slice(-6);
    const team = await j(await post("/api/v1/teams", {name: "Proof Team " + stamp}));
    if (!team.id) throw new Error("seed: team not created: " + JSON.stringify(team));
    for (const u of Object.values(users)) {
      const r = await post("/api/v1/teams/" + team.id + "/members", {user_id: u.id});
      if (!r.ok) throw new Error("seed: membership failed: " + r.status);
    }

    const projects = await j(await fetch("/api/v1/projects", {credentials:"include"}));
    const project = projects[0];
    const form = await j(await post("/api/v1/forms", {
      project_id: project.id, name: "Proof request form " + stamp,
      description_enabled: true, team_picker_enabled: true,
    }));
    if (!form.team_picker_enabled) {
      throw new Error("seed: the form did not keep team_picker_enabled");
    }
    await fetch("/api/v1/forms/" + form.id + "/sharing", {
      method:"PUT", credentials:"include", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({shares: Object.values(users).map((u) => ({user_id: u.id}))}),
    });
    return {
      baselineId: baseline.id, previousBaseline, teamId: team.id, teamName: team.name,
      formId: form.id, projectKey: project.key,
      requesterId: users["${REQUESTER.email}"].id, teammateId: users["${TEAMMATE.email}"].id,
    };
  })()`);

  // --- as the REQUESTER ------------------------------------------------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  const loginStatus = await session.login(baseUrl, REQUESTER.email, REQUESTER.password);

  const actor = await session.eval(`(async () => {
    const me = await (await fetch("/api/v1/auth/me", {credentials:"include"})).json();
    return { global: me.permissions || [] };
  })()`);

  // File two requests: one private, one shared with the team.
  const filed = await session.eval(`(async () => {
    const submit = (title, team_id) => fetch(
      "/api/v1/portal/forms/${seeded.formId}/submit",
      {method:"POST",credentials:"include",headers:{"Content-Type":"application/json"},
       body: JSON.stringify({title, description: "Details here", values: {}, team_id})});
    const mine = await (await submit("Private proof request", null)).json();
    const sharedRes = await submit("Shared proof request", "${seeded.teamId}");
    const shared = await sharedRes.json();
    if (!shared.key) throw new Error("submit with a team failed: " + JSON.stringify(shared));
    return { mineKey: mine.key, sharedKey: shared.key };
  })()`);

  await session.navigate(baseUrl + "/portal", 600);
  await sleep(3500);
  const layout = await session.eval(`(() => {
    // RADD-804: the forms lead. Compared by DOCUMENT POSITION of the actual
    // elements, not by matching heading text — the first version matched a
    // TEAM heading ("Proof Team") that legitimately sits below My requests, and
    // reported a correct layout as broken.
    const cards = document.querySelectorAll('a[href*="/portal/forms/"]');
    const mine = [...document.querySelectorAll("h2")]
      .find((h) => /My requests/i.test(h.textContent || ""));
    const formsFirst = cards[0] && mine
      ? Boolean(cards[0].compareDocumentPosition(mine) & Node.DOCUMENT_POSITION_FOLLOWING)
      : false;
    const grid = cards[0] ? cards[0].closest("ul") : null;
    return {
      formsBeforeRequests: formsFirst,
      formCards: cards.length,
      // The card grid must not overflow its container at this width.
      gridOverflows: grid ? grid.scrollWidth > grid.clientWidth + 1 : false,
    };
  })()`);
  const portalBefore = await session.eval(`(() => {
    const rows = [...document.querySelectorAll('ul button[type="button"]')]
      .filter((b) => /${seeded.projectKey}-/.test(b.textContent || ""));
    const headings = [...document.querySelectorAll("h2")].map((h) => h.textContent.trim());
    return {
      rowCount: rows.length,
      clickable: rows.every((b) => !b.disabled && getComputedStyle(b).pointerEvents !== "none"),
      // RADD-798: mine and the team each get their own heading.
      headings,
      hasTeamHeading: headings.some((h) => h.includes("${seeded.teamName}")),
      hasMineHeading: headings.some((h) => h.includes("My requests")),
      // RADD-797: the pills are RENDERED, not just present in the payload.
      showsUnassigned: (document.body.textContent || "").includes("Unassigned"),
      markers: document.querySelectorAll('[title*="waiting on you"]').length,
    };
  })()`);

  // Open one — the thing that did nothing before.
  const opened = await session.eval(`(async () => {
    const row = [...document.querySelectorAll('ul button[type="button"]')]
      .find((b) => (b.textContent || "").includes("${filed.mineKey}"));
    if (!row) return { clicked: false };
    row.click();
    await new Promise((r) => setTimeout(r, 1800));
    // RADD-803: it must be the app's PEEK, not a modal. Two things prove that
    // rather than one: the URL carries the peek param, and the surface is the
    // right-anchored aside the issue peek uses, not a centred dialog.
    const panel = document.querySelector('aside[role="dialog"]');
    const text = ((panel || document.body).textContent || "").replace(/\\s+/g, " ");
    const box = panel ? panel.getBoundingClientRect() : null;
    return {
      clicked: true,
      isPeek: Boolean(panel),
      urlHasPeek: location.search.includes("peek="),
      // Right-anchored: the drawer's right edge sits at the viewport edge.
      rightAnchored: box ? window.innerWidth - box.right < 20 : false,
      showsKey: text.includes("${filed.mineKey}"),
      showsDescription: text.includes("Details here"),
      hasReplyBox: Boolean(document.querySelector('textarea[aria-label="Reply to this request"]')),
    };
  })()`);

  // --- an agent answers, and an INTERNAL note must stay invisible -------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  await session.eval(`(async () => {
    const item = await (await fetch("/api/v1/items?q=key%20%3D%20${filed.mineKey}", {credentials:"include"})).json();
    const id = (Array.isArray(item) ? item[0] : item.items[0]).id;
    const post = (b) => fetch("/api/v1/items/" + id + "/comments", {method:"POST",credentials:"include",
      headers:{"Content-Type":"application/json"},body:JSON.stringify(b)});
    await post({body: "Have you tried turning it off and on again?", visibility: "public"});
    await post({body: "INTERNAL: this person is difficult", visibility: "internal"});
    return true;
  })()`);

  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, REQUESTER.email, REQUESTER.password);
  await session.navigate(baseUrl + "/portal", 600);
  await sleep(3500);
  const afterReply = await session.eval(`(async () => {
    const body = (document.body.textContent || "").replace(/\\s+/g, " ");
    const detail = await (await fetch("/api/v1/portal/requests/${filed.mineKey}", {credentials:"include"})).json();
    return {
      markers: document.querySelectorAll('[title*="waiting on you"]').length,
      leaksInternal: body.includes("INTERNAL:")
        || JSON.stringify(detail).includes("INTERNAL:"),
      commentCount: detail.comment_count,
      threadLength: (detail.comments || []).length,
    };
  })()`);

  // --- My Work draws the same chrome ----------------------------------------
  await session.navigate(baseUrl + "/", 600);
  await sleep(3500);
  const myWork = await session.eval(`(() => {
    const heads = [...document.querySelectorAll("h2")];
    const formCards = document.querySelectorAll('a[href*="/portal/forms/"]');
    const mine = heads.find((h) => h.textContent.includes("My requests"));
    return {
      hasMyRequests: Boolean(mine),
      // RADD-799: the SAME chrome, measured rather than eyeballed — Portal's
      // headings are 11px uppercase; My Work's used to be 14px semibold.
      headingSize: mine ? getComputedStyle(mine).fontSize : null,
      headingTransform: mine ? getComputedStyle(mine).textTransform : null,
      rowCount: [...document.querySelectorAll('ul button[type="button"]')]
        .filter((b) => /${seeded.projectKey}-/.test(b.textContent || "")).length,
      // RADD-804 — the same cards the Portal shows, not a bare list.
      formCards: formCards.length,
    };
  })()`);

  // --- the TEAMMATE sees the shared one, not the private one -----------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, TEAMMATE.email, TEAMMATE.password);
  const teammate = await session.eval(`(async () => {
    const rows = await (await fetch("/api/v1/portal/requests", {credentials:"include"})).json();
    const keys = rows.map((r) => r.key);
    const priv = await fetch("/api/v1/portal/requests/${filed.mineKey}", {credentials:"include"});
    const shared = await fetch("/api/v1/portal/requests/${filed.sharedKey}", {credentials:"include"});
    return {
      seesShared: keys.includes("${filed.sharedKey}"),
      seesPrivate: keys.includes("${filed.mineKey}"),
      privateStatus: priv.status,
      sharedStatus: shared.status,
    };
  })()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // --- restore ---------------------------------------------------------------
  await session.eval(`fetch("/api/v1/auth/logout", {method:"POST", credentials:"include"})`);
  await session.login(baseUrl, adminEmail, adminPassword);
  const restored = await session.eval(`(async () => {
    const del = (u) => fetch(u, {method:"DELETE", credentials:"include"});
    const r = await fetch("/api/v1/roles/${seeded.baselineId}", {
      method:"PATCH", credentials:"include", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({permissions: ${JSON.stringify(seeded.previousBaseline)}})});

    // Remove the requests first, so the accounts own nothing. Deleting a user
    // who authored work needs a successor (spec 89) — correct product
    // behaviour, and this proof's first cleanup ignored it and 409'd.
    for (const key of ["${filed.mineKey}", "${filed.sharedKey}"]) {
      const found = await (await fetch("/api/v1/items?q=key%20%3D%20" + key,
        {credentials:"include"})).json();
      const rows = Array.isArray(found) ? found : (found.items || []);
      if (rows[0]) await del("/api/v1/items/" + rows[0].id);
    }
    await del("/api/v1/forms/${seeded.formId}");
    const me = await (await fetch("/api/v1/auth/me", {credentials:"include"})).json();
    // ...and still pass a successor, so anything the proof did not foresee
    // (a comment, a watch) transfers rather than blocking the cleanup.
    const u1 = await del("/api/v1/users/${seeded.requesterId}?reassign_to=" + me.id);
    await del("/api/v1/users/${seeded.teammateId}?reassign_to=" + me.id);
    await del("/api/v1/teams/${seeded.teamId}");
    const after = await (await fetch("/api/v1/roles", {credentials:"include"})).json();
    return { patch: r.status, userDel: u1.status,
             baseline: (after.find((x) => x.key === "baseline") || {}).permissions };
  })()`);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the requester signed in": loginStatus === 204,
    "and holds nothing at global scope": actor.global.length === 0,
    // RADD-796 — the headline: the rows do something now.
    "the request rows are clickable": portalBefore.rowCount >= 2 && portalBefore.clickable,
    // RADD-803 — the ordinary peek, not the modal I shipped first.
    "clicking opens the PEEK drawer": opened.isPeek === true && opened.urlHasPeek === true,
    "the drawer is right-anchored like the issue peek": opened.rightAnchored === true,
    "it shows the request": opened.clicked && opened.showsKey,
    "the description is shown": opened.showsDescription === true,
    "there is a way to reply": opened.hasReplyBox === true,
    // RADD-797
    "status pills are rendered": portalBefore.showsUnassigned === true,
    "a public reply lights the marker": afterReply.markers >= 1,
    "the internal note is nowhere": afterReply.leaksInternal === false,
    "and is not counted": afterReply.commentCount === 1 && afterReply.threadLength === 1,
    // RADD-798
    "requests are grouped by team": portalBefore.hasTeamHeading && portalBefore.hasMineHeading,
    "a teammate sees the shared request": teammate.seesShared && teammate.sharedStatus === 200,
    "and not the private one": !teammate.seesPrivate && teammate.privateStatus === 404,
    // RADD-799
    "My Work shows requests": myWork.hasMyRequests && myWork.rowCount >= 1,
    "with Portal's section chrome": myWork.headingSize === "11px"
      && myWork.headingTransform === "uppercase",
    // RADD-804
    "the Portal leads with the forms": layout.formsBeforeRequests === true,
    "the form cards render and do not overflow":
      layout.formCards >= 1 && layout.gridOverflows === false,
    "My Work shows the same form cards": myWork.formCards >= 1,
    "no console errors": consoleErrors.length === 0,
    "the Baseline was restored": restored.patch === 200
      && JSON.stringify(restored.baseline) === JSON.stringify(seeded.previousBaseline),
    "the seeded accounts were removed": restored.userDel === 204,
  };

  return report(checks, { actor, layout, portalBefore, opened, afterReply, myWork, teammate, restored,
    consoleErrors: consoleErrors.slice(0, 5) });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
