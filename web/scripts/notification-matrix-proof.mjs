/**
 * Render proof for the scoped notification matrix (spec 118, RADD-1055). What tsc cannot see:
 *  - it lays out as a matrix: one row per SERVER kind, one cell per relationship column, columns
 *    aligned across rows (a bad gridTemplateColumns or a failed fetch both type-check);
 *  - a PERSONAL kind's other columns are disabled (it follows the Mine column);
 *  - every unset cell shows what the server would actually deliver — not "off", and not the Mine
 *    column's answer on a subscription cell;
 *  - a cell edit round-trips: hit-tested click, PUT, cache, re-render;
 *  - both themes (the lit/unlit marks are the only carrier of the value).
 * The account's rules are read first and PUT back verbatim.
 *
 * Usage: node scripts/notification-matrix-proof.mjs <baseUrl> <email> <password>
 */
import { resolve } from "node:path";
import { outputPath, report, sleep } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PREFS = "/api/v1/notifications/preferences";
/** `NOTIFICATION_KINDS` members — 13 since spec 118 added created / updated /
 *  page_created. A literal, because the proof runs in a browser against a built
 *  bundle and has no import of the vocabulary; a check that accepted "some rows"
 *  would not notice the vocabulary failing to arrive, which is what this exists
 *  to catch. */
const KIND_COUNT = 13;
/** own / participating / teams. */
const SCOPE_COUNT = 3;

/** The matrix's own state, measured rather than assumed. */
const READ_MATRIX = `(() => {
  const grid = document.querySelector("[data-notification-matrix]");
  if (!grid) return { rows: [], headers: [] };
  const cells = [...grid.querySelectorAll("[data-channel]")].map((el) => {
    const r = el.getBoundingClientRect();
    return {
      label: el.getAttribute("aria-label") || "",
      channel: el.getAttribute("data-channel"),
      inherited: el.getAttribute("data-inherited"),
      disabled: el.getAttribute("data-channel") === "disabled",
      x: Math.round(r.left),
      y: Math.round(r.top),
      w: Math.round(r.width),
      h: Math.round(r.height),
    };
  });
  const rows = new Map();
  for (const cell of cells) {
    const [kind, scope] = cell.label.split(" — ");
    const row = rows.get(kind) || { kind, cells: [] };
    row.cells.push({ ...cell, scope });
    rows.set(kind, row);
  }
  const headers = [...grid.querySelectorAll("span")]
    .map((s) => (s.textContent || "").trim())
    .filter((t) => ["Mine", "Following", "My teams"].includes(t));
  return { rows: [...rows.values()], headers, gridWidth: Math.round(grid.getBoundingClientRect().width) };
})()`;

const SET_THEME = (theme) => `(() => {
  document.documentElement.classList.toggle("light", ${JSON.stringify(theme)} === "light");
  return document.documentElement.className;
})()`;

const SHOT = async (session, name, context) => {
  const path = outputPath(name);
  await session.screenshot(path);
  context.screenshots = [...(context.screenshots || []), path];
};

async function main() {
  const { session, close, baseUrl, hoverCapable } = await startProof({
    port: 9457, profile: resolve(process.env.TMPDIR || "/tmp", "radd-notification-matrix-proof"),
  });
  const checks = { "headless chrome reports a real pointer": hoverCapable };
  const context = {};

  const original = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{credentials:"include"});return r.json();})()`,
  );
  context.kindsFromServer = (original.kinds || []).length;
  context.scopesFromServer = original.scopes;
  checks["the preferences read carries the kind VOCABULARY"] =
    Array.isArray(original.kinds) && original.kinds.length === KIND_COUNT;
  checks["…and the relationship scopes"] =
    Array.isArray(original.scopes) && original.scopes.length === SCOPE_COUNT;
  checks["…and the defaults an unset cell inherits"] =
    Boolean(original.defaults && original.defaults.own);

  await session.navigate(`${baseUrl}/settings/notifications`, 3000);
  let matrix = { rows: [] };
  for (let i = 0; i < 20; i++) {
    await sleep(400);
    matrix = await session.eval(READ_MATRIX);
    if (matrix.rows.length) break;
  }
  context.rows = matrix.rows.length;
  checks["every kind has a row"] = matrix.rows.length === KIND_COUNT;
  checks["…with a cell per relationship column"] =
    matrix.rows.every((r) => r.cells.length === SCOPE_COUNT);
  checks["…under the three column headers"] = matrix.headers.length === SCOPE_COUNT;

  // A matrix, not a list: each column holds ONE x across every row, and a row's
  // cells share a baseline.
  const columnXs = [0, 1, 2].map((i) => new Set(matrix.rows.map((r) => r.cells[i].x)));
  context.columnXs = columnXs.map((s) => [...s]);
  checks["…in three straight columns"] = columnXs.every((set) => set.size === 1);
  checks["…each row on one line"] = matrix.rows.every(
    (r) => Math.max(...r.cells.map((c) => c.y)) - Math.min(...r.cells.map((c) => c.y)) <= 1,
  );
  checks["…left to right"] =
    [...columnXs[0]][0] < [...columnXs[1]][0] && [...columnXs[1]][0] < [...columnXs[2]][0];
  // A cell people have to hit: 24px is the floor an affordance has to clear.
  const smallest = Math.min(...matrix.rows.flatMap((r) => r.cells.map((c) => Math.min(c.w, c.h))));
  context.smallestCell = smallest;
  checks["…and every cell is a real target (>= 20px)"] = smallest >= 20;

  // --- personal kinds resolve through `own` alone ---
  const personalLabels = original.kinds.filter((k) => k.personal).map((k) => k.label);
  const ambientLabels = original.kinds.filter((k) => !k.personal).map((k) => k.label);
  context.personal = personalLabels.length;
  const personalRows = matrix.rows.filter((r) => personalLabels.includes(r.kind));
  checks["every personal kind is on the page"] = personalRows.length === personalLabels.length;
  checks["…with its Mine cell live"] = personalRows.every((r) => !r.cells[0].disabled);
  checks["…and the other two columns disabled"] = personalRows.every(
    (r) => r.cells[1].disabled && r.cells[2].disabled,
  );
  const ambientRows = matrix.rows.filter((r) => ambientLabels.includes(r.kind));
  checks["an ambient kind has three live cells"] = ambientRows.every((r) =>
    r.cells.every((c) => !c.disabled),
  );

  // --- inheritance is shown, not hidden ---
  const untouched = matrix.rows.flatMap((r) => r.cells).filter((c) => !c.disabled);
  checks["an unset cell reports itself INHERITED"] = untouched.some(
    (c) => c.inherited === "true",
  );
  // …and it resolves to the documented default rather than to `off`.
  const assignedRow = matrix.rows.find((r) => r.kind === "Assigned to me");
  context.assignedOwn = assignedRow && assignedRow.cells[0];
  checks["…resolving to the default, not to off"] =
    Boolean(assignedRow) && assignedRow.cells[0].channel === "both";

  // --- a cell edit round-trips ---
  const target = ambientRows.find((r) => r.cells[0].channel !== "email");
  context.target = target && target.kind;
  checks["a cell is available to change"] = Boolean(target);
  const hit = await session.click(`[aria-label="${target.cells[0].label}"]`);
  context.menuTriggerHit = hit.hitIsInsideTarget;
  checks["…and the trigger is not covered by anything"] = hit.hitIsInsideTarget === true;
  await sleep(300);
  const opened = await session.eval(
    `document.querySelectorAll('[role="menuitem"]').length`,
  );
  context.menuItems = opened;
  checks["…its menu opens with five choices"] = opened === 5;

  await session.click('[role="menuitem"]', (text) => text.trim() === "Email only");
  let changed = null;
  for (let i = 0; i < 20; i++) {
    await sleep(400);
    const now = await session.eval(READ_MATRIX);
    changed = now.rows.find((r) => r.kind === target.kind);
    if (changed && changed.cells[0].channel === "email") break;
  }
  context.afterEdit = changed && changed.cells[0];
  checks["…the choice round-trips through the API"] =
    Boolean(changed) && changed.cells[0].channel === "email";
  checks["…and the cell stops reading as inherited"] =
    Boolean(changed) && changed.cells[0].inherited === "false";
  const stored = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{credentials:"include"});return r.json();})()`,
  );
  const ownRule = (stored.rules || []).find((r) => r.scope === "own");
  context.storedOwnRule = ownRule;
  checks["…and the SERVER stored an `own` rule for it"] = Boolean(
    ownRule && Object.values(ownRule.channels).includes("email"),
  );

  // --- a subscription is added, edited and removed ---
  //
  // The reach the whole spec exists for, so it gets the same treatment as the
  // matrix: a real click through hit-testing, a real PUT, and the row read back
  // off the re-rendered page rather than off what was clicked.
  // Counted as a DELTA, never against zero: this proof promises to leave the
  // account as it found it, which means it must also START from whatever the
  // account already has. An absolute assertion passed on a clean instance and
  // failed the moment a run left one behind — which is the same bug the promise
  // is about, caught from the other side.
  const subscriptionKey = (rule) => `${rule.scope}:${rule.scope_id}`;
  const beforeKeys = new Set(
    (original.rules || []).filter((r) => r.scope_id).map(subscriptionKey),
  );
  const before = await session.eval(`document.querySelectorAll("[data-subscription]").length`);
  context.subscriptionsBefore = before;
  // The target picker is a dialog with one button per target (RADD-1115); an empty
  // directory says "No matching subscription targets." instead.
  await session.click('[aria-label="Subscription target"]');
  let targets = null;
  for (let i = 0; i < 20 && !targets?.settled; i++) {
    await sleep(300);
    targets = await session.eval(`(() => {
      const dialog = document.querySelector('[role="dialog"][aria-label^="Subscribe to a"]');
      if (!dialog) return null;
      const rows = dialog.querySelectorAll("ul li button").length;
      return { rows, settled: rows > 0 || /No matching subscription targets/.test(dialog.textContent || "") };
    })()`);
  }
  context.subscriptionPicker = targets;
  const hasTargets = Boolean(targets?.rows);
  checks["the subscription picker offers something to subscribe to"] = hasTargets;
  if (targets && !hasTargets) await session.click('[role="dialog"] [aria-label="Close"]');
  if (hasTargets) {
    // Scoped to the DIALOG: an unscoped `li button` once matched a nav item earlier in the
    // document, and the proof clicked it and navigated away.
    await session.click('[role="dialog"] ul li button');
    await sleep(300);
    await session.click("button", (text) => text.trim() === "Add");
    let added = before;
    for (let i = 0; i < 20; i++) {
      await sleep(400);
      added = await session.eval(
        `document.querySelectorAll("[data-subscription]").length`,
      );
      if (added > before) break;
    }
    context.subscriptionsAfter = added;
    checks["…adding one renders one more subscription card"] = added === before + 1;
    const seeded = await session.eval(
      `(async()=>{const r=await fetch("${PREFS}",{credentials:"include"});const p=await r.json();` +
        `return (p.rules||[]).filter((x)=>x.scope_id).map((x)=>({scope:x.scope,scope_id:x.scope_id,label:x.scope_label,kinds:Object.keys(x.channels)}));})()`,
    );
    context.storedSubscriptions = seeded;
    checks["…the server stored it with a resolved NAME"] =
      seeded.length === added && seeded.every((row) => Boolean(row.label));

    // Exactly ONE kind, and the right one. Seeding every ambient kind meant
    // eight switched on per click — "hear about new issues" also asked for every
    // comment, state change, field edit, SLA timer and wiki event. And the
    // arrival kind is per scope: `created` is planned from ITEM events, which
    // carry no space, so a space subscription seeded with it would look
    // configured and deliver nothing.
    const fresh = seeded.find((row) => !beforeKeys.has(subscriptionKey(row)));
    context.newSubscription = fresh;
    const expectedSeed = fresh && fresh.scope === "space" ? "page_created" : "created";
    checks["…seeded with exactly the ONE kind that scope is for"] =
      Boolean(fresh) && fresh.kinds.length === 1 && fresh.kinds[0] === expectedSeed;

    // …and every other kind on that card reads OFF, inherited. The resolver
    // gives a subscription's unset cell the SUBSCRIPTION scope's default: this
    // person has no other relation to that project, so the subscription is the
    // only applicable scope and `off` is what would actually be delivered. The
    // page used to show the "Mine" column's value here, which described a
    // notification that never arrives.
    const cells = fresh
      ? await session.eval(`(() => {
          const card = document.querySelector('[data-subscription="${fresh.scope_id}"]');
          if (!card) return null;
          return [...card.querySelectorAll("[data-channel]")].map((el) => ({
            label: el.getAttribute("aria-label") || "",
            channel: el.getAttribute("data-channel"),
            inherited: el.getAttribute("data-inherited"),
          }));
        })()`)
      : null;
    context.newSubscriptionCells = cells;
    checks["…and its card renders a cell per ambient kind"] =
      Array.isArray(cells) && cells.length === original.kinds.filter((k) => !k.personal).length;
    const set = (cells || []).filter((c) => c.inherited === "false");
    const unset = (cells || []).filter((c) => c.inherited === "true");
    checks["…exactly one cell reads as SET, and it is on"] =
      set.length === 1 && set[0].channel === "inbox";
    checks["…every unset cell resolves to off, not to the Mine column"] =
      unset.length > 0 && unset.every((c) => c.channel === "off");
  }

  // --- both themes ---
  for (const theme of ["dark", "light"]) {
    await session.eval(SET_THEME(theme));
    await sleep(400);
    const themed = await session.eval(READ_MATRIX);
    checks[`the matrix still measures as a matrix in ${theme}`] =
      themed.rows.length === KIND_COUNT &&
      themed.rows.every((r) => r.cells.length === SCOPE_COUNT);
    await SHOT(session, `notification-matrix-${theme}.png`, context);
  }
  await session.eval(SET_THEME("dark"));

  // --- leave nothing behind ---
  const restore = { rules: (original.rules || []).map((r) => ({ scope: r.scope, scope_id: r.scope_id, channels: r.channels })), email_digest: original.email_digest };
  const restored = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{method:"PUT",credentials:"include",` +
      `headers:{"Content-Type":"application/json"},` +
      `body:JSON.stringify(${JSON.stringify(restore)})});return r.json();})()`,
  );
  checks["the account's own rules are put back"] =
    JSON.stringify(restored.rules) === JSON.stringify(original.rules);

  // Plugin REMOTES are built into the image by `build-all.mjs`, so a bundle
  // built with a bare `vite build` 404s every one and quarantines it loudly.
  // That is a property of how the proof's server was started, not of this page,
  // and folding it into the check would either fail every local run or teach
  // everyone to ignore the line — which is how a real error gets through.
  const ours = session.consoleErrors.filter((line) => !line.includes("[radd] plugin UI"));
  context.consoleErrors = ours.slice(0, 5);
  context.quarantinedPluginRemotes = session.consoleErrors.length - ours.length;
  checks["the page logged no console errors of its own"] = ours.length === 0;

  const failed = report(checks, context);
  close();
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
