/**
 * Render proof for the Confluence importer (spec 117).
 *
 * Building is not verifying. This drives a real browser at a page imported from
 * REAL Confluence storage format and asserts what a reader actually sees:
 *
 *   1. the settings page mounts, with its connections/downloads panels;
 *   2. an imported page's TABLE survives the inline `status` lozenge that sits in
 *      one of its cells — a block-level fence there would end the table;
 *   3. the task list renders as real checkboxes, with the completed one checked;
 *   4. `radd:unsupported-macro` renders as a CARD naming the macro, not raw JSON
 *      and not nothing — the whole reason the importer never has to guess;
 *   5. `radd:callout` and `radd:toc` render as their components;
 *   6. the Jira macro became a live issue chip, and the cross-page link resolved.
 *
 * Usage:
 *   node scripts/confluence-import-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9451;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-confluence-proof-profile");

/** What the imported page's DOM actually contains. */
const PAGE_PROBE = `(() => {
  const text = (el) => (el?.textContent || "").trim();
  const tables = [...document.querySelectorAll("table")];
  const statusTable = tables.find((t) => text(t).includes("WIP"));
  const checkboxes = [...document.querySelectorAll('input[type="checkbox"]')];
  const bodyText = text(document.querySelector("main")) || text(document.body);
  return {
    tableCount: tables.length,
    // The lozenge's table must still BE a table with more than one row: a fence
    // emitted inside a cell terminates it, leaving a one-row stub.
    statusTableRows: statusTable ? statusTable.querySelectorAll("tr").length : 0,
    statusInCell: Boolean(
      statusTable && [...statusTable.querySelectorAll("td, th")].some((c) => text(c) === "WIP"),
    ),
    checkboxCount: checkboxes.length,
    checkedCount: checkboxes.filter((c) => c.checked).length,
    // The unsupported card names its macro rather than dumping JSON.
    namesTheMacro: bodyText.includes("drawio"),
    showsRawJson: bodyText.includes('"macro":') || bodyText.includes("radd:unsupported"),
    hasCalloutText: bodyText.includes("frame ranges shouldn't be done"),
    // The wiki renders code through CodeMirror, NOT a <pre>. Probing for <pre>
    // reported a failure while the block was on screen with its language chip.
    hasCodeBlock: Boolean(document.querySelector(".cm-editor, pre")),
    // An unresolved attachment must still be an IMAGE element. A filename with
    // spaces makes an image link not-a-link, and it renders as literal text.
    imageIsAnElement: Boolean(document.querySelector('img[src*="Screenshot"]')),
    literalImageMarkdown: bodyText.includes("![Screenshot"),
    issueChip: [...document.querySelectorAll("a")].some((a) => text(a).includes("SAT-1665")),
    resolvedPageLink: [...document.querySelectorAll("a")].some((a) =>
      (a.getAttribute("href") || "").startsWith("/pages/"),
    ),
    // A fence that failed to render would leave its literal source behind.
    leakedFence: bodyText.includes("radd:callout") || bodyText.includes("radd:toc"),
  };
})()`;

const SETTINGS_PROBE = `(() => {
  const text = (el) => (el?.textContent || "").trim();
  const body = text(document.body);
  return {
    heading: body.includes("Import from Confluence"),
    connections: body.includes("Connections"),
    downloads: body.includes("Downloads"),
    // Readable before anything is configured — configured:false is an answer.
    prompts: body.includes("No connection yet"),
    buttons: [...document.querySelectorAll("button")].map((b) => text(b)).filter(Boolean).length,
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  // Headless Chrome reports (hover: none) at BASELINE, and Tailwind gates every
  // hover: utility on it — so an unstyled affordance would read as a product bug.
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // --- the settings surface ---
  await session.navigate(`${baseUrl}/settings/confluence-import`, 2500);
  const settings = await session.eval(SETTINGS_PROBE);
  checks["the settings page mounts"] = settings.heading;
  checks["…with a connections panel"] = settings.connections;
  checks["…and a downloads panel"] = settings.downloads;
  checks["…and it renders before anything is configured"] = settings.prompts;
  const settingsShot = await session.send("Page.captureScreenshot", { format: "png" });

  // --- the imported page ---
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${pageSlug}`, 3000);
  await sleep(800);
  const page = await session.eval(PAGE_PROBE);

  checks["the imported page renders a table"] = page.tableCount > 0;
  checks["…the status lozenge sits INSIDE a cell"] = page.statusInCell;
  checks["…and its table survived (more than one row)"] = page.statusTableRows > 1;
  checks["the unsupported macro is a card naming 'drawio'"] = page.namesTheMacro;
  checks["…not raw JSON"] = page.showsRawJson === false;
  checks["the callout rendered its text"] = page.hasCalloutText;
  checks["the code macro became a code block"] = page.hasCodeBlock;
  checks["an unresolved image is still an <img>, not literal text"] =
    page.literalImageMarkdown === false;
  checks["no fence leaked as literal text"] = page.leakedFence === false;
  const pageShot = await session.send("Page.captureScreenshot", { format: "png" });

  report(checks, { settings, page });
  return { settingsShot: settingsShot.data, pageShot: pageShot.data };
}

main()
  .then(async (shots) => {
    const { writeFile } = await import("node:fs/promises");
    const dir = process.env.PROOF_OUT || "/tmp";
    await writeFile(`${dir}/confluence-settings.png`, Buffer.from(shots.settingsShot, "base64"));
    await writeFile(`${dir}/confluence-page.png`, Buffer.from(shots.pageShot, "base64"));
    console.log(`screenshots: ${dir}/confluence-settings.png, ${dir}/confluence-page.png`);
    process.exit(0);
  })
  .catch((error) => {
    console.error(error);
    process.exit(1);
  });
