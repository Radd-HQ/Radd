/**
 * Render proof for Settings → Email (RADD-958; presets RADD-969).
 *
 * The page is mostly forms, and forms are where "it compiles" is furthest from
 * "it works". Four things are asserted because each has already been a bug in
 * this codebase, or would be invisible to `tsc`:
 *
 *  - the nav entry and route resolve (a page nobody can reach is not shipped);
 *  - the Server overview's Email row LINKS here — the ask that started this;
 *  - a secret never appears in the DOM. `has_secret` is a boolean by design,
 *    and the day someone adds `value={source.secret}` nothing would fail;
 *  - the kind picker actually CHANGES the form (RADD-969). The preset branch is
 *    a conditional render driven by a fetched catalog: a broken query, a renamed
 *    wire field or a kind mismatch all type-check and all leave the connection
 *    fields showing — which reads as "the preset does nothing".
 *
 * Usage: node scripts/mail-settings-proof.mjs <baseUrl> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, email, password] = process.argv.slice(2);
const PORT = 9455;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-mail-settings-proof");

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE });
  const checks = {};

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  checks["headless chrome reports a real pointer"] = await session.hoverCapable();

  // --- the overview row links here (the ask) ---
  await session.navigate(`${baseUrl}/settings/instance`, 2500);
  const overview = await session.eval(`(() => {
    const row = [...document.querySelectorAll("a")]
      .find((a) => /email/i.test(a.textContent || "") && /settings\\/email/.test(a.getAttribute("href") || ""));
    return { present: Boolean(row), href: row ? row.getAttribute("href") : null };
  })()`);
  checks["the Server overview Email row links to Settings → Email"] = overview.present;

  // --- the page itself ---
  await session.navigate(`${baseUrl}/settings/email`, 3000);
  let page = { heading: false };
  for (let i = 0; i < 20; i++) {
    await sleep(500);
    page = await session.eval(`(() => {
      const text = document.body.innerText;
      return {
        heading: /Where mail arrives/i.test(text),
        incoming: /Incoming/.test(text),
        outgoing: /Outgoing/.test(text),
        addSource: Boolean([...document.querySelectorAll("button")]
          .find((b) => /add source/i.test(b.textContent || ""))),
        addSender: Boolean([...document.querySelectorAll("button")]
          .find((b) => /add sender/i.test(b.textContent || ""))),
        denied: /instance-admin access/i.test(text),
      };
    })()`);
    if (page.heading || page.denied) break;
  }
  checks["the page renders"] = page.heading === true;
  checks["…with an Incoming section"] = page.incoming === true;
  checks["…and an Outgoing section"] = page.outgoing === true;
  checks["…offering to add a source"] = page.addSource === true;
  checks["…and a sender"] = page.addSender === true;

  // --- the source form opens and never shows a stored secret ---
  // Scoped to the DIALOG, not the document: the page's own info banner mentions
  // app passwords, so a body-wide regex would pass whether the guidance
  // rendered or not — a check that cannot fail is worse than no check.
  const readForm = () =>
    session.eval(`(() => {
      const dialog = document.querySelector('[role="dialog"]');
      if (!dialog) return { open: false };
      const labels = [...dialog.querySelectorAll("label")].map((l) => l.textContent || "");
      const pw = [...dialog.querySelectorAll('input[type="password"]')];
      const text = dialog.innerText;
      return {
        open: /New mail source/i.test(text),
        hasKind: labels.some((l) => /where mail comes from/i.test(l)),
        hasDefaultProject: labels.some((l) => /default project/i.test(l)),
        // The preset branch: hidden connection fields + the app-password note.
        hasHost: labels.some((l) => /^host$/i.test(l.trim())),
        hasPort: labels.some((l) => /^port$/i.test(l.trim())),
        guidance: /app password/i.test(text),
        guidanceLink: Boolean(dialog.querySelector('a[href*="support."]')),
        appPasswordLabel: labels.some((l) => /app password/i.test(l)),
        passwordFields: pw.length,
        // A password input pre-filled from the server is the failure this guards.
        prefilled: pw.some((i) => (i.value || "").length > 0),
      };
    })()`);

  let form = { open: false };
  let custom = { hasHost: false };
  let presetShot = null;
  if (page.addSource) {
    await session.click("button", (t) => /add source/i.test(t));
    await sleep(900);
    form = await readForm();
    presetShot = await session.send("Page.captureScreenshot", { format: "png" });

    // Switch the kind to the hand-configured IMAP one: the connection fields
    // must COME BACK. Asserting only that Gmail hides them would pass just as
    // well if the fields were never rendered at all.
    await session.click("button", (t) => /gmail/i.test(t));
    await sleep(300);
    await session.click('[role="option"]', (t) => /IMAP mailbox/i.test(t));
    await sleep(500);
    custom = await readForm();
  }
  checks["the source form opens"] = form.open === true;
  checks["…asks where mail comes from"] = form.hasKind === true;
  checks["…and a default project"] = form.hasDefaultProject === true;
  checks["…with an empty password field, never a stored one"] =
    form.passwordFields > 0 && form.prefilled === false;
  checks["Gmail hides the connection fields it answers itself"] =
    form.hasHost === false && form.hasPort === false;
  checks["…and states the app-password precondition, with a link"] =
    form.guidance === true && form.appPasswordLabel === true && form.guidanceLink === true;
  checks["a plain IMAP mailbox asks for host and port"] =
    custom.hasHost === true && custom.hasPort === true;
  checks["…and drops the preset's guidance with it"] = custom.guidance === false;

  const shot = await session.send("Page.captureScreenshot", { format: "png" });
  checks["no console errors"] = session.consoleErrors.length === 0;

  const failed = report(checks, {
    overview,
    page,
    form,
    custom,
    consoleErrors: session.consoleErrors.slice(0, 5),
  });
  const { writeFileSync } = await import("node:fs");
  writeFileSync("/tmp/mail-settings.png", Buffer.from(shot.data, "base64"));
  if (presetShot) {
    writeFileSync("/tmp/mail-settings-preset.png", Buffer.from(presetShot.data, "base64"));
    console.log("shot: /tmp/mail-settings-preset.png (the Gmail form)");
  }
  console.log("shot: /tmp/mail-settings.png");
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
