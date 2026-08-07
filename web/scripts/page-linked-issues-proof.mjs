/**
 * Render proof for a page's Linked issues section (RADD-943 / RADD-944).
 *
 * Three claims, none of which a clean `tsc` could reach:
 *
 *  - **Issues named in the body are listed without anyone typing a key**, and
 *    those rows carry no unlink button. An X that reappears on the next save
 *    would be a lie about who owns the link.
 *  - **The section is shut when it has nothing.** It used to spend ~90px on
 *    every page in the wiki saying "no linked issues yet" beside an input. The
 *    check measures the section's HEIGHT, not the chevron's state: a collapse
 *    that toggles `aria-expanded` while staying full height is a bug this
 *    codebase has already shipped once (RADD-746).
 *  - **"In this section" is gone** (RADD-944) — from a page that HAS children,
 *    or the assertion passes for the wrong reason.
 *
 * Usage:
 *   node scripts/page-linked-issues-proof.mjs <baseUrl> <spaceSlug> <linkedSlug> <emptySlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, linkedSlug, emptySlug, email, password] = process.argv.slice(2);
const PORT = 9451;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-linked-issues-proof");

/** Runs IN the page. One round trip for everything the assertions need. */
const PROBE = `(() => {
  const heading = [...document.querySelectorAll('button[aria-expanded]')]
    .find((b) => /linked issues/i.test(b.textContent || ""));
  if (!heading) return { present: false };
  const section = heading.closest("section");
  const rows = [...section.querySelectorAll("li")];
  const bodyText = document.body.innerText;
  return {
    present: true,
    expanded: heading.getAttribute("aria-expanded") === "true",
    // The measurement, not the attribute: a section that reports collapsed and
    // still occupies the page has not collapsed.
    sectionHeight: Math.round(section.getBoundingClientRect().height),
    countChip: (heading.textContent.match(/\\d+/) || [null])[0],
    rows: rows.map((li) => ({
      key: (li.querySelector("span.font-mono") || {}).textContent || "",
      hasUnlink: !!li.querySelector('[aria-label^="Unlink"]'),
      marker: /in the text/i.test(li.textContent || ""),
    })),
    hasAddForm: !!section.querySelector('input[aria-label="Issue key"]'),
    // RADD-944. Read from the whole document, not the section — and paired
    // with childCount below, because "no index" on a page with no children is
    // the assertion passing for the wrong reason.
    inThisSection: /in this section/i.test(bodyText),
    // The tree rail is where children belong now, and it says so whether or not
    // the branch is expanded: a collapsed parent carries an Expand control.
    treeChildOf: !!document.querySelector(
      '[data-page-tree] [aria-label="Expand Mentions"], [data-page-tree] [aria-label="Collapse Mentions"]',
    ),
    // The prose reference that must NOT have produced a link.
    mentionsProseOnlyKey: /SV7SY-1/.test(bodyText),
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // --- the page whose text names two issues ---
  // Collapsed FIRST (RADD-945), so the rows are read only after a real click:
  // the count chip renders while shut, the rows do not.
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${linkedSlug}`, 1000);
  let linked = { present: false };
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    linked = await session.eval(PROBE);
    if (linked.present && linked.countChip === "2") break;
  }

  checks["the section is present"] = linked.present;
  checks["the count chip reports both links while shut"] = linked.countChip === "2";
  // RADD-945: collapsed means collapsed, links or no links. The chip is what
  // makes that acceptable — it is how a reader knows there is anything here.
  checks["it starts collapsed even WITH links"] = linked.expanded === false;
  checks["…rendering no rows at all until asked"] = linked.rows.length === 0;
  checks["…and no add form"] = linked.hasAddForm === false;

  await session.click('button[aria-expanded]', (t) => /linked issues/i.test(t));
  await sleep(400);
  const expanded = await session.eval(PROBE);

  checks["one click opens it"] = expanded.expanded === true;
  checks["both mentioned issues are listed, unasked"] = expanded.rows.length === 2;
  checks["no derived row offers an unlink button"] =
    expanded.rows.length > 0 && expanded.rows.every((r) => !r.hasUnlink);
  checks["each derived row says where it came from"] =
    expanded.rows.length > 0 && expanded.rows.every((r) => r.marker);
  checks["the editor token form linked"] = expanded.rows.some((r) => r.key === "GRX-100918");
  checks["the URL form linked"] = expanded.rows.some((r) => r.key === "GRX-100917");
  checks["a key named in PROSE did not link"] =
    expanded.mentionsProseOnlyKey && !expanded.rows.some((r) => r.key.startsWith("SV7SY"));
  checks["a writer can still add one by hand"] = expanded.hasAddForm;
  // The RADD-944 pair. The first makes the second mean something: asserting
  // "no subpage index" on a page with no subpages proves nothing at all.
  checks["the page under test HAS a child"] = linked.treeChildOf === true;
  checks["…and grows no automatic In this section"] = !linked.inThisSection;

  const linkedShot = await session.send("Page.captureScreenshot", { format: "png" });

  // --- the page whose text names none ---
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${emptySlug}`, 2500);
  let empty = { present: false };
  for (let i = 0; i < 30; i++) {
    await sleep(400);
    empty = await session.eval(PROBE);
    if (empty.present) break;
  }
  checks["an empty section still offers its heading"] = empty.present;
  checks["…collapsed"] = empty.expanded === false;
  checks["…with no count chip"] = empty.countChip === null;
  // The whole point: a heading row and its border, nothing else. The old panel
  // was ~90px here.
  checks["…and it costs under 50px"] = empty.sectionHeight > 0 && empty.sectionHeight < 50;
  checks["…hiding the add form until asked for"] = empty.hasAddForm === false;

  const emptyShot = await session.send("Page.captureScreenshot", { format: "png" });
  checks["no console errors"] = session.consoleErrors.length === 0;

  const failed = report(checks, {
    collapsed: { expanded: linked.expanded, chip: linked.countChip, rows: linked.rows.length },
    expanded: { expanded: expanded.expanded, rows: expanded.rows },
    empty: { expanded: empty.expanded, sectionHeight: empty.sectionHeight },
    consoleErrors: session.consoleErrors.slice(0, 5),
  });

  const { writeFileSync } = await import("node:fs");
  writeFileSync("/tmp/linked-issues-linked.png", Buffer.from(linkedShot.data, "base64"));
  writeFileSync("/tmp/linked-issues-empty.png", Buffer.from(emptyShot.data, "base64"));
  console.log("\nshots: /tmp/linked-issues-linked.png /tmp/linked-issues-empty.png");
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
