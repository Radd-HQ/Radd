/**
 * Proves RADD-751: images resize, in pages AND comments, and a resized image
 * actually transfers fewer bytes.
 *
 * That last clause is the one worth being careful about. "It looks smaller" is
 * satisfied by a CSS width and would leave the 4 MB screenshot problem exactly
 * where it was, so this measures the RESPONSE — same attachment, with and
 * without `?w=` — rather than the rendered box.
 *
 * Usage: node scripts/image-resize-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9457;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-image-proof");

/** Poll for an element instead of guessing at a sleep. */
async function waitFor(session, selector, tries = 24) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(`!!document.querySelector(${JSON.stringify(selector)})`)) return true;
    await sleep(250);
  }
  return false;
}

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  // A page holding a genuinely large PNG, uploaded through the real endpoint.
  const setup = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let page = pages.find((p) => p.slug === "image-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Image proof", body: "seed\\n" }),
      })).json();
    }
    // 2000x1400 of NOISE — a flat fill compresses to nothing and would make the
    // byte comparison meaningless.
    const canvas = document.createElement("canvas");
    canvas.width = 2000; canvas.height = 1400;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(2000, 1400);
    for (let i = 0; i < img.data.length; i += 4) {
      img.data[i] = (i * 7) % 256;
      img.data[i+1] = (i * 13) % 256;
      img.data[i+2] = (i * 29) % 256;
      img.data[i+3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
    // entity_type/entity_id are FORM fields, not query parameters.
    const form = new FormData();
    form.append("file", blob, "big.png");
    form.append("entity_type", "page");
    form.append("entity_id", page.id);
    const response = await fetch("/api/v1/attachments", {
      method: "POST", credentials: "include", body: form,
    });
    const uploaded = await response.json();
    if (!uploaded.id) return { uploadError: response.status, detail: uploaded };
    const src = "/api/v1/attachments/" + uploaded.id;
    await fetch("/api/v1/pages/" + page.id, {
      method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ body: "intro\\n\\n![shot](" + src + ")\\n" }),
    });
    return { id: page.id, slug: page.slug, src, attachment: uploaded.id };
  })()`);

  if (setup.uploadError) {
    console.error('upload failed:', JSON.stringify(setup, null, 2));
    return 1;
  }

  // --- the byte claim, measured at the endpoint ----------------------------
  //
  // The ORIGINAL size comes from the attachment record, not from fetching it.
  // This instance's default host delivers PRESIGNED, so an un-widened request is
  // a 307 to the object store on another origin, which `fetch` cannot read
  // without CORS — an `<img>` does not care, but a measurement does. That is
  // also the observation that makes the width request interesting: honouring a
  // width forces the PROXY path, so the resized bytes come from us.
  const bytes = await session.eval(`(async () => {
    const get = async (url) => (await (await fetch(url, {credentials:"include"})).blob()).size;
    const record = await (await fetch(
      "/api/v1/attachments?entity_type=page&entity_id=${setup.id}", {credentials:"include"})).json();
    const mine = record.find((a) => a.id === "${setup.attachment}");
    const small = await get("${setup.src}?w=480");
    const medium = await get("${setup.src}?w=1024");
    // A width past the original must fall THROUGH to normal delivery, which on
    // this host is a redirect — an opaqueredirect is exactly that, observed.
    const past = await fetch("${setup.src}?w=4000", {credentials:"include", redirect:"manual"});
    const head = await fetch("${setup.src}?w=480", {credentials:"include"});
    return {
      full: mine ? mine.size_bytes : 0,
      small, medium,
      pastOriginalType: past.type,
      contentType: head.headers.get("content-type"),
      cache: head.headers.get("cache-control"),
    };
  })()`);
  // What the browser actually decoded, so "smaller" is not just fewer bytes of
  // the same picture.
  const decoded = await session.eval(`(async () => {
    const load = (url) => new Promise((res) => {
      const i = new Image();
      i.onload = () => res({ w: i.naturalWidth, h: i.naturalHeight });
      i.onerror = () => res(null);
      i.src = url;
    });
    return { full: await load("${setup.src}"), small: await load("${setup.src}?w=480") };
  })()`);

  // --- resizing in a PAGE ---------------------------------------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${setup.slug}`, 3000);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(2500);
  const inEditor = await session.eval(`(() => {
    const block = document.querySelector(".ProseMirror [data-image-block]");
    return {
      present: !!block,
      handle: !!document.querySelector("[data-image-handle]"),
      crepeImages: document.querySelectorAll(".milkdown-image-block").length,
      width: block ? block.getAttribute("data-width") : null,
    };
  })()`);

  // Drag the handle 700px to the LEFT of the image's right edge.
  const drag = await session.eval(`(() => {
    const h = document.querySelector("[data-image-handle]");
    const img = document.querySelector(".ProseMirror [data-image-block] img");
    if (!h || !img) return null;
    const r = h.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2, imgWidth: img.getBoundingClientRect().width };
  })()`);
  if (drag) {
    await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: drag.x, y: drag.y });
    await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: drag.x, y: drag.y, button: "left", clickCount: 1 });
    await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: drag.x - 380, y: drag.y, button: "left", buttons: 1 });
    await sleep(200);
    await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: drag.x - 380, y: drag.y, button: "left", clickCount: 1 });
  }
  await sleep(700);
  const afterDrag = await session.eval(`(() => {
    const block = document.querySelector(".ProseMirror [data-image-block]");
    const img = block ? block.querySelector("img") : null;
    return {
      width: block ? block.getAttribute("data-width") : null,
      renderedWidth: img ? Math.round(img.getBoundingClientRect().width) : 0,
      srcset: img ? img.getAttribute("srcset") : null,
      src: img ? img.getAttribute("src") : null,
    };
  })()`);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2400);
  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${setup.id}", {credentials:"include"})).json()).body)()`);

  // --- and it SURVIVES a reload, in read mode ------------------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${setup.slug}`, 2000);
  await waitFor(session, "[data-image-block] img");
  const inReadMode = await session.eval(`(() => {
    const block = document.querySelector("[data-image-block]");
    const anyImg = [...document.querySelectorAll("img")].map((i) => i.getAttribute("src")).slice(0, 6);
    const viewers = document.querySelectorAll(".radd-rich-viewer").length;
    const img = block ? block.querySelector("img") : null;
    return {
      width: block ? block.getAttribute("data-width") : null,
      renderedWidth: img ? Math.round(img.getBoundingClientRect().width) : 0,
      handle: !!document.querySelector("[data-image-handle]"),
      anyImg, viewers,
    };
  })()`);

  // --- and in a COMMENT ----------------------------------------------------
  const comment = await session.eval(`(async () => {
    const created = await (await fetch("/api/v1/page/${setup.id}/comments", {
      method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ body: "look:\\n\\n![shot](${setup.src}?w=320)\\n" }),
    })).json();
    return { id: created.id };
  })()`);
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${setup.slug}`, 2000);
  // Comments mount on approach (the thread is lazy), so scroll to the bottom
  // and then wait for the image rather than assuming a sleep covers both.
  await session.eval(`window.scrollTo(0, document.body.scrollHeight)`);
  await waitFor(session, "[data-image-block][data-width='320'] img");
  const inComment = await session.eval(`(() => {
    const blocks = [...document.querySelectorAll("[data-image-block]")];
    const commented = blocks.find((b) => b.getAttribute("data-width") === "320");
    const img = commented ? commented.querySelector("img") : null;
    return {
      found: !!commented,
      renderedWidth: img ? Math.round(img.getBoundingClientRect().width) : 0,
      blocks: blocks.length,
    };
  })()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);
  const width = Number(afterDrag.width || 0);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    // The claim that makes this worth doing at all.
    "a narrower image transfers fewer bytes": bytes.small > 0 && bytes.small < bytes.full,
    "and a wider request transfers more than a narrow one": bytes.medium > bytes.small,
    "a width past the original falls through to normal delivery":
      bytes.pastOriginalType === "opaqueredirect",
    "the resized bytes really are a smaller picture":
      decoded.small?.w === 480 && decoded.full?.w === 2000,
    "it is still an image, served inline": /^image\//.test(bytes.contentType || ""),
    "a resized variant is cacheable": /immutable/.test(bytes.cache || ""),
    "the editor renders our image view": inEditor.present === true && inEditor.crepeImages === 0,
    "an attachment image offers a resize handle": inEditor.handle === true,
    "dragging sets a width": width > 0 && width < 2000,
    "and the image is drawn at it": Math.abs(afterDrag.renderedWidth - width) <= 2,
    // The width has to be IN THE MARKDOWN, or nothing above survives a save.
    "the width is written into the URL, keeping the body markdown":
      (saved || "").includes("![shot](/api/v1/attachments/") &&
      (saved || "").includes("?w=" + width + ")"),
    "no HTML leaked into the body": !/<img/i.test(saved || ""),
    "the size survives a reload": Number(inReadMode.width) === width,
    "read mode offers no handle": inReadMode.handle === false,
    "a comment's image is resized too": inComment.found === true && Math.abs(inComment.renderedWidth - 320) <= 2,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { setup, bytes, decoded, inEditor, drag, afterDrag, saved, inReadMode, comment, inComment, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
