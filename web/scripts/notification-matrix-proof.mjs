/**
 * Render proof for the notification channel matrix (RADD-686).
 *
 * `tsc` and `vite build` cannot see any of what matters here:
 *
 *  - that the grid actually LAYS OUT as a matrix — two labelled columns over
 *    one row of two checkboxes per notification type. A wrong `grid-cols`
 *    template type-checks and ships a single column of stray boxes;
 *  - that Email is DISABLED and reads unchecked while Inbox is off. That is the
 *    whole "email requires inbox" rule at the surface, and it is a runtime
 *    property of a `disabled` attribute driven by fetched state — a broken
 *    query, a renamed wire field or an inverted set test all compile;
 *  - that a click ROUND-TRIPS: the PUT lands, the response is written into the
 *    cache, and the row re-renders from it. The panel was previously an inline
 *    query with a hand-written key, so nothing here is proved by the old one.
 *
 * The account's real preferences are read first and PUT back verbatim at the
 * end, so a proof run against a live dev instance leaves no residue.
 *
 * Usage: node scripts/notification-matrix-proof.mjs <baseUrl> <email> <password>
 */
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9457;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-notification-matrix-proof");
const PREFS = "/api/v1/notifications/preferences";
const SHOT = resolve(process.env.TMPDIR || "/tmp", "notification-matrix.png");
/** `NotificationType` members — bump with the enum (10 since RADD-978's
 *  `participant_added`). A literal, because the proof runs in a browser against
 *  a built bundle and has no import of the TS enum; a check that silently
 *  accepts "some rows" would not notice a type losing its row, which is what
 *  this one exists to catch. */
const NOTIFY_TYPE_COUNT = 10;

/** The panel's own state, measured rather than assumed. */
const READ_MATRIX = `(() => {
  const boxes = [...document.querySelectorAll('input[type="checkbox"][aria-label]')]
    .filter((b) => /— (in my inbox|by email)/.test(b.getAttribute("aria-label")));
  const rows = new Map();
  for (const box of boxes) {
    const [label, channel] = box.getAttribute("aria-label").split(" — ");
    const row = rows.get(label) || { label };
    row[/inbox/.test(channel) ? "inbox" : "email"] = {
      checked: box.checked,
      disabled: box.disabled,
      x: Math.round(box.getBoundingClientRect().left),
      y: Math.round(box.getBoundingClientRect().top),
    };
    rows.set(label, row);
  }
  const headers = [...document.querySelectorAll("span")]
    .map((s) => (s.textContent || "").trim())
    .filter((t) => t === "Inbox" || t === "Email");
  return { rows: [...rows.values()], headers };
})()`;

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};
  const context = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // The account's real prefs, restored at the end.
  const original = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{credentials:"include"});return r.json();})()`,
  );
  context.originalPrefs = original;
  checks["GET /notifications/preferences carries email_types"] =
    Array.isArray(original.email_types);

  await session.navigate(`${baseUrl}/settings/profile`, 3000);
  let matrix = { rows: [] };
  for (let i = 0; i < 20; i++) {
    await sleep(400);
    matrix = await session.eval(READ_MATRIX);
    if (matrix.rows.length) break;
  }
  context.rows = matrix.rows.length;
  checks["every notification type has a row"] = matrix.rows.length === NOTIFY_TYPE_COUNT;
  checks["…under an Inbox and an Email column header"] =
    matrix.headers.includes("Inbox") && matrix.headers.includes("Email");
  // A matrix, not a list: the two boxes of a row share a baseline, and the two
  // columns hold their x across every row.
  const inboxXs = new Set(matrix.rows.map((r) => r.inbox.x));
  const emailXs = new Set(matrix.rows.map((r) => r.email.x));
  checks["…in two straight columns"] = inboxXs.size === 1 && emailXs.size === 1;
  checks["…with the two boxes of a row on one line"] = matrix.rows.every(
    (r) => Math.abs(r.inbox.y - r.email.y) <= 1,
  );
  checks["…and Email to the right of Inbox"] = [...emailXs][0] > [...inboxXs][0];

  // --- email requires inbox ---
  const target = matrix.rows.find((r) => r.inbox.checked);
  context.target = target ? target.label : null;
  checks["a row is available to toggle"] = Boolean(target);
  checks["…whose Email box is live while its Inbox box is on"] =
    target && target.email.disabled === false;

  await session.click(
    `input[aria-label="${target.label} — in my inbox"]`,
  );
  let toggled = null;
  for (let i = 0; i < 20; i++) {
    await sleep(400);
    const now = await session.eval(READ_MATRIX);
    toggled = now.rows.find((r) => r.label === target.label);
    if (toggled && toggled.inbox.checked === false) break;
  }
  context.afterMute = toggled;
  checks["muting a type round-trips through the API"] =
    Boolean(toggled) && toggled.inbox.checked === false;
  checks["…and disables its Email box"] = Boolean(toggled) && toggled.email.disabled === true;
  checks["…which reads unchecked, not merely dimmed"] =
    Boolean(toggled) && toggled.email.checked === false;
  const stored = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{credentials:"include"});return r.json();})()`,
  );
  context.storedAfterMute = stored;

  // Scrolled into view before the shot: an image that stops at the section
  // heading proves the page loaded, not that the matrix looks like one.
  await session.eval(`(() => {
    const boxes = [...document.querySelectorAll('input[type="checkbox"][aria-label]')]
      .filter((b) => /— by email/.test(b.getAttribute("aria-label")));
    if (boxes.length) boxes[boxes.length - 1].scrollIntoView({ block: "center" });
    return boxes.length;
  })()`);
  await sleep(600);
  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(SHOT, Buffer.from(shot.data, "base64"));
  context.screenshot = SHOT;

  // --- leave nothing behind ---
  const restored = await session.eval(
    `(async()=>{const r=await fetch("${PREFS}",{method:"PUT",credentials:"include",` +
      `headers:{"Content-Type":"application/json"},` +
      `body:JSON.stringify(${JSON.stringify(original)})});return r.json();})()`,
  );
  checks["the account's own preferences are put back"] =
    JSON.stringify(restored) === JSON.stringify(original);

  const failed = report(checks, context);
  close();
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
