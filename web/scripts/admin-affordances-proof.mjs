/**
 * Render proof for three controls that either lied or were missing
 * (RADD-947 / RADD-949 / RADD-950).
 *
 * Each of these is invisible to `tsc`, and each failed in a way that reads as
 * "the product cannot do this" rather than as a bug:
 *
 *  - **The page-restrict dialog offered a project Scope** on a resource whose
 *    spec says `project_scoped=false` and whose write path answers "page grants
 *    can't be scoped". The check is paired: the SAME editor must still show the
 *    picker for a custom field, or "no scope control" passes because the editor
 *    is broken everywhere.
 *  - **A select field's options could only grow.** Removing one must ask where
 *    its items go, with the count in the question.
 *  - **Settings → Labels had no rename or delete** and said the API lacked them.
 *
 * Usage:
 *   node scripts/admin-affordances-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);
const PORT = 9453;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-admin-affordances-proof");

/** What a grants editor is currently offering, wherever it is mounted.
 *
 *  Selected by ARIA label, not by visible text: `ScopePicker` renders a
 *  TokenMultiSelect whose placeholder is "Global — everywhere", so hunting for
 *  the word "scope" found nothing and reported a missing control on a screen
 *  that had one. */
const GRANTS_PROBE = `(() => {
  const access = document.querySelector('[aria-label="Access level"]');
  const row = access ? access.parentElement : null;
  return {
    hasAccessSelect: Boolean(access),
    hasScopeControl: Boolean(document.querySelector('[aria-label="Project scope"]')),
    // The row reads "<subject> may <access> on <scope>"; with no scope there
    // must be no dangling "on". Searched document-wide rather than among the
    // select's siblings: the Select component wraps itself, so the access
    // control's parentElement is its own wrapper, not the sentence.
    saysOn: [...document.querySelectorAll("span")].some(
      (el) => (el.textContent || "").trim() === "on",
    ),
    row: Boolean(row),
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // --- RADD-947: the page-restrict dialog ---
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${pageSlug}`, 2500);
  await session.click('[aria-label="Restrict page"]');
  await sleep(1200);
  const pageGrants = await session.eval(GRANTS_PROBE);
  checks["the restrict dialog mounts the grants editor"] = pageGrants.hasAccessSelect;
  checks["…offering NO project scope (page grants can't be scoped)"] =
    pageGrants.hasScopeControl === false;
  checks["…and no dangling \"on\""] = pageGrants.saysOn === false;
  const restrictShot = await session.send("Page.captureScreenshot", { format: "png" });

  // --- and the SAME editor on a resource that IS scopeable ---
  // Without this, "no scope control" would pass just as well if the editor were
  // broken outright.
  await session.navigate(`${baseUrl}/settings/fields`, 3000);
  let fieldGrants = { hasScopeControl: false };
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    fieldGrants = await session.eval(GRANTS_PROBE);
    if (fieldGrants.hasAccessSelect) break;
  }
  checks["the same editor still scopes a custom field"] =
    fieldGrants.hasAccessSelect && fieldGrants.hasScopeControl === true;
  checks["…and still says \"on\" there"] = fieldGrants.saysOn === true;

  // --- RADD-949: removing a select option ---
  const optionUi = await session.eval(`(() => {
    const removers = [...document.querySelectorAll('[aria-label^="Remove option"]')];
    return { count: removers.length, first: removers[0]?.getAttribute("aria-label") || null };
  })()`);
  checks["select options offer a remove control"] = optionUi.count > 0;

  let dialog = { open: false };
  if (optionUi.count > 0) {
    await session.click('[aria-label^="Remove option"]');
    await sleep(1500);
    dialog = await session.eval(`(() => {
      const text = document.body.innerText;
      return {
        open: /Remove "/.test(text),
        // The count comes from a dry run — the question has to carry its number.
        statesUsage: /item(s)? (hold|list) this option|No items use this option/i.test(text),
        offersDestination: Boolean(
          [...document.querySelectorAll("label")].find((l) =>
            /move those items to/i.test(l.textContent || ""))),
        offersEmpty: /leave empty/i.test(text),
      };
    })()`);
  }
  checks["…which opens a dialog rather than removing silently"] = dialog.open === true;
  checks["…that states how many items are affected"] = dialog.statesUsage === true;
  const optionShot = await session.send("Page.captureScreenshot", { format: "png" });

  // --- RADD-950: labels ---
  await session.navigate(`${baseUrl}/settings/labels`, 3000);
  let labels = { rename: 0, del: 0, stale: true };
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    labels = await session.eval(`(() => ({
      rename: document.querySelectorAll('[aria-label^="Edit "]').length,
      del: document.querySelectorAll('[aria-label^="Delete "]').length,
      stale: /isn.t supported by the API/i.test(document.body.innerText),
    }))()`);
    if (labels.rename > 0) break;
  }
  checks["labels offer rename"] = labels.rename > 0;
  checks["labels offer delete"] = labels.del > 0;
  checks["…and no longer claim the API lacks them"] = labels.stale === false;
  const labelShot = await session.send("Page.captureScreenshot", { format: "png" });

  checks["no console errors"] = session.consoleErrors.length === 0;

  const failed = report(checks, {
    pageGrants,
    fieldGrants: { mounted: fieldGrants.hasAccessSelect, scope: fieldGrants.hasScopeControl },
    optionUi,
    dialog,
    labels,
    consoleErrors: session.consoleErrors.slice(0, 5),
  });

  const { writeFileSync } = await import("node:fs");
  writeFileSync("/tmp/admin-restrict.png", Buffer.from(restrictShot.data, "base64"));
  writeFileSync("/tmp/admin-option.png", Buffer.from(optionShot.data, "base64"));
  writeFileSync("/tmp/admin-labels.png", Buffer.from(labelShot.data, "base64"));
  console.log("\nshots: /tmp/admin-restrict.png /tmp/admin-option.png /tmp/admin-labels.png");
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
