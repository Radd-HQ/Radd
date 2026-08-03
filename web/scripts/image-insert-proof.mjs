/**
 * Proves RADD-760: the toolbar's Image button leads somewhere.
 *
 * `image-resize-proof.mjs` seeds images that already have a URL, so it never
 * exercised the state the toolbar actually produces — an image node with no
 * src. Crepe's ImageBlock used to render an uploader for that state; turning it
 * off in RADD-751 left a bare `<img>` with nothing in it, a 0x0 element, and no
 * `input[type=file]` anywhere in the document. Clicking Image did nothing you
 * could see, which is what "attachments stopped working" meant.
 *
 * So the assertions are about the EMPTY state, and the one that matters most is
 * the count of file inputs — the whole defect was expressible as `=== 0`.
 *
 * Usage: node scripts/image-insert-proof.mjs <baseUrl> <spaceSlug> <email> <password> [pngPath]
 */
import { resolve } from "node:path";
import { writeFileSync } from "node:fs";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password, pngArg] = process.argv.slice(2);
const PORT = 9459;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-image-insert-proof");

/** A real 2x2 PNG, written out so the file picker has something to pick. */
function samplePng() {
  if (pngArg) return pngArg;
  const path = resolve(TMP, "radd-image-insert-proof.png");
  writeFileSync(
    path,
    Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFElEQVR4nGP8z8Dwn4GBgYkBBTAy" +
        "AAB1qAMBn2Y2nAAAAABJRU5ErkJggg==",
      "base64",
    ),
  );
  return path;
}

const CARD = `(() => {
  const pm = document.querySelector(".ProseMirror");
  const card = pm.querySelector("[data-image-empty]");
  const box = card ? card.getBoundingClientRect() : null;
  return {
    present: !!card,
    height: box ? Math.round(box.height) : 0,
    width: box ? Math.round(box.width) : 0,
    fileInputs: pm.querySelectorAll('input[type=file]').length,
    urlInputs: pm.querySelectorAll('input[type=url]').length,
    // A 0x0 <img> is what the bug rendered — it must not be what we render now.
    zeroSizeImages: [...pm.querySelectorAll("img")].filter(
      (i) => i.getBoundingClientRect().height === 0,
    ).length,
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let page = pages.find((p) => p.slug === "image-insert-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Image insert proof", body: "seed\\n" }),
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
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);

  // --- the toolbar button must produce something usable --------------------
  await session.click('[role="toolbar"] button[data-toolbar-action="image"]');
  await sleep(900);
  const card = await session.eval(CARD);

  // --- typing in the URL field must not reach the document -----------------
  const typing = await session.eval(`(() => {
    const pm = document.querySelector(".ProseMirror");
    const before = pm.textContent;
    const input = pm.querySelector('input[type=url]');
    input.focus();
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "x", bubbles: true }));
    return { kept: document.activeElement === input, unchanged: pm.textContent === before };
  })()`);

  // --- a real file, chosen the way the file dialog would deliver it ---------
  await session.send("DOM.enable");
  const { root } = await session.send("DOM.getDocument", { depth: -1, pierce: true });
  const { nodeId } = await session.send("DOM.querySelector", {
    nodeId: root.nodeId,
    selector: ".ProseMirror input[type=file]",
  });
  if (nodeId) {
    await session.send("DOM.setFileInputFiles", { nodeId, files: [samplePng()] });
  }
  await sleep(3500);

  const uploaded = await session.eval(`(async () => {
    const pm = document.querySelector(".ProseMirror");
    const img = pm.querySelector("img");
    // naturalWidth is the honest "the bytes arrived and decoded" signal. A
    // cross-origin fetch() of a presigned URL is CORS-blocked; an <img> is not.
    if (img && !img.complete) await new Promise((r) => { img.onload = r; img.onerror = r; });
    return {
      src: img ? img.getAttribute("src") : null,
      naturalWidth: img ? img.naturalWidth : 0,
      cardGone: !pm.querySelector("[data-image-empty]"),
      cardText: pm.querySelector("[data-image-empty]")?.textContent ?? null,
    };
  })()`);

  // --- and it must survive the save as ordinary markdown -------------------
  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the Image button yields a visible card": card.present === true && card.height > 40,
    // The defect, stated as the number it was.
    "the card carries a file input": card.fileInputs === 1,
    "the card carries a URL field": card.urlInputs === 1,
    "nothing renders as a zero-height image": card.zeroSizeImages === 0,
    "the URL field keeps focus and keystrokes": typing.kept === true && typing.unchanged === true,
    "choosing a file replaces the card": uploaded.cardGone === true,
    "the upload reports no error": uploaded.cardText === null,
    "the image points at an attachment": /\/attachments\//.test(uploaded.src || ""),
    "the browser decoded real bytes": uploaded.naturalWidth > 0,
    "the body is still plain markdown": /!\[[^\]]*\]\(/.test(saved || ""),
    "no console errors": consoleErrors.length === 0,
  };

  const failed = report(checks, {
    card,
    typing,
    uploaded: { ...uploaded, src: (uploaded.src || "").slice(0, 60) },
    savedTail: (saved || "").slice(-90),
    consoleErrors: consoleErrors.slice(0, 3),
  });
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
