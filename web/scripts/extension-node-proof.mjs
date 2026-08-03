/**
 * Proves RADD-746: a `radd:*` fence is a real editor NODE, not a code block.
 *
 * The insert proof already covers "picking an entry writes a fence". What it
 * cannot see is the thing this issue is about — that in EDIT mode the fence
 * renders as the block it describes, with chrome to reconfigure it, and that
 * saving a block nobody touched writes the markdown back unchanged.
 *
 * Four assertions carry the issue:
 *
 *  - the editor contains `[data-extension-editable]` and NO `radd:` code block
 *    (the fence was claimed at parse time, so the code-block view never saw it);
 *  - the rendered callout text is on screen while editing;
 *  - the hover chrome exists and its Configure button is what is PAINTED at its
 *    own coordinates (element.click() cannot see a z-index bug — RADD-742);
 *  - an untouched block round-trips byte-identically, and an edited one saves
 *    the new parameters.
 *
 * Usage: node scripts/extension-node-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9451;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ext-node-proof");

/** The seed body. Deliberately includes a fenced ```markdown example holding a
 *  `radd:toc` line: that is documentation, not an extension, and must stay a
 *  code block — the parse-time claim inspects the fence's own lang, so this is
 *  the case that tells a real transform from a regex sweep. */
const SEED = [
  "# Heading one",
  "",
  "```radd:callout",
  '{"kind": "warning", "title": "Mind the gap", "text": "Body text."}',
  "```",
  "",
  "````markdown",
  "```radd:toc",
  "```",
  "````",
  "",
  "tail prose",
  "",
].join("\n");

async function main() {
  const { session, close } = await openBrowser({
    port: PORT, profile: PROFILE, width: 1440, height: 1100,
  });
  const { consoleErrors } = session;

    await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "node-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Node proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  const before = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  await session.send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${created.slug}` });
  await sleep(2500);

  await session.eval(
    `(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);

  // What the EDITOR contains. `.ProseMirror` scopes every query to editor-owned
  // DOM, so a read-mode block below cannot make this pass by accident.
  const inEditor = await session.eval(`(() => {
    const pm = [...document.querySelectorAll(".ProseMirror")];
    const q = (sel) => pm.flatMap((root) => [...root.querySelectorAll(sel)]);
    const nodes = q("[data-extension-editable]");
    // A code block is a <pre> only until CodeMirror's mode loads and then it is
    // a .cm-editor with no <pre> at all — so look for BOTH shapes, and for the
    // fence's own text, rather than for one of them.
    const codeish = [...q("pre"), ...q(".cm-editor")];
    return {
      nodeCount: nodes.length,
      names: nodes.map((n) => n.getAttribute("data-extension")),
      renderedText: nodes.map((n) => (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 80)),
      codeBlockCount: codeish.length,
      // The fenced markdown EXAMPLE must survive as code — its text is the tell.
      codeBlockText: codeish.map((n) => (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 40)),
      // No editor-owned element may still be showing the raw fence header.
      rawFenceVisible: pm.some((root) => (root.textContent || "").includes("radd:callout")),
      chromeButtons: q('button[aria-label^="Configure radd:"]').length,
    };
  })()`);

  // Hover, then click Configure — through the input pipeline, so a chrome row
  // painted under something else fails here rather than passing quietly.
  await session.hover(".ProseMirror [data-extension-editable]");
  await sleep(400);
  // Read the CHROME ROW, not the button: opacity does not inherit, so
  // `getComputedStyle(button).opacity` is 1 whether or not the row is hidden —
  // an assertion on it passes against a chrome nobody can see.
  const configureVisible = await session.eval(`(() => {
    const b = document.querySelector('button[aria-label^="Configure radd:"]');
    if (!b) return null;
    const row = b.parentElement;
    const s = getComputedStyle(row);
    const r = b.getBoundingClientRect();
    return {
      rowOpacity: s.opacity,
      rowPointerEvents: s.pointerEvents,
      blockHovered: !!document.querySelector("[data-extension-editable]:hover"),
      rowInsideHoveredGroup: !!row.closest(".group:hover"),
      groupIsHovered: !!document.querySelector(".group:hover"),
      // Assert the emulation took: if this is false every hover assertion
      // below is meaningless, and should say so rather than reading as a bug.
      hoverCapable: matchMedia("(hover: hover)").matches,
      width: r.width, height: r.height,
      buttonPadding: getComputedStyle(b).padding,
      buttonClass: String(b.className).slice(0, 60),
    };
  })()`);
  const configureHit = await session.click('button[aria-label^="Configure radd:"]');
  await sleep(700);

  const dialog = await session.eval(`(() => {
    const d = document.querySelector('[role="dialog"]');
    if (!d) return null;
    const ta = d.querySelector("textarea");
    return {
      label: d.getAttribute("aria-label"),
      // The dialog must open on the block's ACTUAL parameters, not on defaults.
      value: ta ? ta.value : null,
      hasPreview: /Preview/.test(d.textContent || ""),
    };
  })()`);

  // Change a parameter and save the block. Defensive rather than throwing: a
  // missing textarea is a RESULT this proof should report, not a crash that
  // hides every assertion after it.
  const retyped = await session.eval(`(() => {
    const ta = document.querySelector('[role="dialog"] textarea');
    if (!ta) return false;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    setter.call(ta, JSON.stringify({ kind: "danger", title: "Mind the gap", text: "Body text.", unknown_param: 7 }));
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  })()`);
  await sleep(300);
  if (retyped) await session.click('[role="dialog"] button', (t) => t.trim() === "Save");
  await sleep(700);

  const afterEdit = await session.eval(`(() => {
    const n = document.querySelector(".ProseMirror [data-extension-editable]");
    return n ? (n.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 80) : null;
  })()`);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);

  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  // Round-trip with NOTHING touched: re-seed, open, save, compare.
  await session.eval(`(async () => {
    await fetch("/api/v1/pages/${created.id}", {
      method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ body: ${JSON.stringify(SEED)} }),
    });
  })()`);
  await session.send("Page.navigate", { url: `${baseUrl}/pages/${spaceSlug}/${created.slug}` });
  await sleep(2500);
  await session.eval(
    `(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);
  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const untouched = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const checks = {
    "the fence became an editor node": inEditor.nodeCount === 1 && inEditor.names[0] === "callout",
    "no editor element still shows the raw radd: fence": inEditor.rawFenceVisible === false,
    "the callout renders live while editing": /Mind the gap/.test(inEditor.renderedText.join(" ")),
    "a ```markdown example stays a code block":
      inEditor.codeBlockCount === 1 && inEditor.codeBlockText.join(" ").includes("radd:toc"),
    "hover chrome exists": inEditor.chromeButtons === 1,
    "the browser reports a hover-capable pointer": configureVisible?.hoverCapable === true,
    "hovering the block reveals the chrome":
      configureVisible?.blockHovered === true && configureVisible?.rowOpacity === "1",
    // Crepe's unlayered `.milkdown button { border: none; background: none }`
    // strips utility styling from any button inside the editor, and `p-1`
    // resolved to 0 there — the affordance was a 13x13 target before this.
    "the chrome buttons are a usable target":
      (configureVisible?.width ?? 0) >= 24 && (configureVisible?.height ?? 0) >= 24,
    "the Configure button is what is painted at its own coordinates":
      configureHit.hitIsInsideTarget === true,
    "the dialog opens on the block's actual parameters":
      dialog !== null && /Mind the gap/.test(dialog.value || ""),
    "the dialog previews the block": dialog?.hasPreview === true,
    "editing re-renders the block in place": afterEdit !== null && /Mind the gap/.test(afterEdit),
    "the edit is written back as a radd:callout fence": /```radd:callout/.test(saved || ""),
    "the edited parameter is persisted": /"kind":\s*"danger"/.test(saved || ""),
    "an unknown parameter is preserved, not dropped": /unknown_param/.test(saved || ""),
    "an untouched block round-trips byte-identically": untouched === before,
    "no console errors": consoleErrors.length === 0,
  };

  return {
    failed: report(checks, { inEditor, configureVisible, configureHit, dialog, retyped,
                             afterEdit, saved, untouched, consoleErrors }),
    close,
  };
}

main()
  .then(({ failed, close }) => { process.exit(failed ? 1 : 0); })
  .catch((err) => { console.error(err); process.exit(2); });
