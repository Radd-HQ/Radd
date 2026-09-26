/**
 * Proves the RADD-709 insert menu: the toolbar button opens a picker built from
 * `GET /pages/extensions`, and choosing an entry inserts a real ```radd:<name>
 * fence into the editor — pre-filled from the spec's schema defaults.
 *
 * The assertion that matters is the LAST one: after picking, the page's saved
 * markdown must contain the fence. A menu that opens and inserts nothing would
 * pass every other check.
 *
 * Usage: node scripts/extension-insert-proof.mjs <baseUrl> <spaceSlug> <pageSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, pageSlug, email, password] = process.argv.slice(2);

async function main() {
  const { session, close } = await openBrowser({
    port: 9448, profile: resolve(process.env.TMPDIR || "/tmp", "radd-ext-insert-proof"),
  });
  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  // A scratch page of its own, so the proof never edits the render-proof page.
  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let page = pages.find((p) => p.slug === "insert-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Insert proof", body: "seed\\n" }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: "seed\\n" }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);

  // Enter edit mode.
  const enteredEdit = await session.eval(`(() => {
    const btn = document.querySelector('button[aria-label="Edit page"]');
    if (!btn) return false;
    btn.click();
    return true;
  })()`);
  await sleep(2500);

  const toolbarButtonPresent = await session.eval(`!!document.querySelector("svg.radd-extension-toolbar-icon")`);

  await session.click("svg.radd-extension-toolbar-icon");
  await sleep(900);

  // Compare against what the SERVER offers rather than a number baked in here —
  // the registry grows as extensions land, and a hardcoded threshold just goes
  // stale and starts failing correct code.
  const menu = await session.eval(`(async () => {
    const items = [...document.querySelectorAll('[role="menu"] [role="menuitem"]')];
    const declared = await (await fetch("/api/v1/pages/extensions", {credentials:"include"})).json();
    return {
      count: items.length,
      declared: declared.length,
      labels: items.map((i) => i.textContent.trim().slice(0, 40)),
    };
  })()`);

  // Pick "Callout" — it has a schema with defaults, so the inserted block must
  // arrive pre-filled rather than empty. Real input, at real coordinates.
  const picked = await session.click('[role="menu"] [role="menuitem"]', (t) => t.includes("Callout"));
  await sleep(900);

  // Save, then read the persisted markdown back from the API — the only proof
  // that survives the round trip.
  await session.eval(`(() => {
    const save = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save");
    save && save.click();
  })()`);
  await sleep(2000);

  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const hoverCapable = await session.hoverCapable();
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "entered edit mode": enteredEdit === true,
    "extension toolbar button is present": toolbarButtonPresent === true,
    "the picker lists exactly what the registry declares":
      menu.declared > 0 && menu.count === menu.declared,
    "picker shows the Callout entry": menu.labels.some((l) => l.includes("Callout")),
    // The assertion that would have caught the overlay bug: what is PAINTED at
    // the click point has to be the menu item itself.
    "the menu item is what is painted at the click point": picked.hitIsInsideTarget === true,
    "a radd:callout fence was inserted and saved": /```radd:callout/.test(saved || ""),
    "the block arrived pre-filled from the schema defaults": /"kind":\s*"info"/.test(saved || ""),
    "no console errors": session.consoleErrors.length === 0,
  };
  const failed = report(checks, { menu, picked, saved, consoleErrors: session.consoleErrors });
  await close();
  return failed;
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
