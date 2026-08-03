/**
 * Proves RADD-752: the code block is ours, in both modes.
 *
 * The assertion the issue is really about is the LAST pair: read mode and edit
 * mode must render code identically, because `RichViewer` exists to preserve
 * exactly that. Two components that merely agree today is how they drift.
 *
 * It also pins the timing that made an older proof flaky. A code block is a
 * `<pre>` only until the mode finishes loading, after which it is a `.cm-editor`
 * with no `<pre>` at all. Owning the node view means owning when that happens,
 * so this waits for the highlight to appear and then asserts on it.
 *
 * Usage: node scripts/code-block-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9455;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-code-block-proof");

const CODE = [
  "def greet(name):",
  '    """Say hello."""',
  "    count = 42",
  "    return f'hello {name} {count}'",
].join("\n");

const SEED = ["intro paragraph", "", "```python", CODE, "```", ""].join("\n");

/** Everything worth knowing about the code block on the current page. */
const PROBE = `(() => {
  const block = document.querySelector("[data-code-block]");
  if (!block) return { present: false };
  const cm = block.querySelector(".cm-editor");
  const content = block.querySelector(".cm-content");
  // Highlighted tokens carry a lezer class AND a resolved colour. Counting
  // spans alone would pass on a mode that loaded and coloured nothing.
  const tokens = [...block.querySelectorAll(".cm-line span")]
    .map((s) => ({ text: s.textContent, color: getComputedStyle(s).color }))
    .filter((t) => t.text.trim());
  const distinctColors = [...new Set(tokens.map((t) => t.color))];
  return {
    present: true,
    language: block.getAttribute("data-language"),
    isCmEditor: !!cm,
    stillPre: !!block.querySelector("pre"),
    crepeBlocks: document.querySelectorAll(".milkdown-code-block").length,
    text: content ? content.textContent : "",
    tokenCount: tokens.length,
    distinctColors,
    hasCopy: !!block.querySelector(".radd-code-copy"),
    hasPicker: !!block.querySelector('button[aria-haspopup="listbox"]'),
    languageLabel: block.querySelector('button[aria-haspopup="listbox"], .radd-code-block span')
      ? (block.querySelector('button[aria-haspopup="listbox"]') || block.querySelector("span")).textContent.trim()
      : null,
    fontFamily: content ? getComputedStyle(content).fontFamily : "",
    lineCount: block.querySelectorAll(".cm-line").length,
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
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "code-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Code proof", body }),
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

  // --- READ mode -----------------------------------------------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 3000);
  // The mode loads asynchronously; wait for the highlight rather than guessing.
  for (let i = 0; i < 20; i++) {
    const ready = await session.eval(
      `!!document.querySelector("[data-code-block] .cm-line span")`);
    if (ready) break;
    await sleep(250);
  }
  const read = await session.eval(PROBE);

  // --- EDIT mode -----------------------------------------------------------
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(2500);
  for (let i = 0; i < 20; i++) {
    const ready = await session.eval(
      `!!document.querySelector(".ProseMirror [data-code-block] .cm-line span")`);
    if (ready) break;
    await sleep(250);
  }
  const edit = await session.eval(PROBE);

  // Copy: read the clipboard back, rather than trusting the button's label.
  await session.send("Browser.grantPermissions", {
    origin: baseUrl,
    permissions: ["clipboardReadWrite", "clipboardSanitizedWrite"],
  }).catch(() => {});
  await session.click("[data-code-block] .radd-code-copy");
  await sleep(600);
  const clipboard = await session.eval(`navigator.clipboard.readText()`).catch(() => null);

  // Change the language through the picker.
  await session.click('[data-code-block] button[aria-haspopup="listbox"]');
  await sleep(500);
  await session.click('[role="listbox"] [role="option"]', (t) => t.trim() === "JavaScript");
  await sleep(800);
  const afterLanguage = await session.eval(PROBE);

  // Typing inside the block must reach the document.
  await session.click("[data-code-block] .cm-content");
  await sleep(200);
  for (const type of ["keyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", {
      type, key: "End", code: "End", windowsVirtualKeyCode: 35,
    });
  }
  await session.send("Input.insertText", { text: "  # typed" });
  await sleep(600);

  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2400);
  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);
  const normalise = (s) => (s || "").replace(/\s+/g, " ").trim();

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "read mode renders our code block": read.present === true,
    "edit mode renders our code block": edit.present === true,
    "no Crepe code block anywhere": read.crepeBlocks === 0 && edit.crepeBlocks === 0,
    // The timing lesson, asserted rather than tripped over.
    "the mode loaded: it is a .cm-editor, not a <pre>":
      read.isCmEditor === true && read.stillPre === false,
    "code is highlighted, in more than one colour":
      read.tokenCount > 3 && read.distinctColors.length >= 3,
    // The property RichViewer exists for.
    "read and edit show the same code": normalise(read.text) === normalise(edit.text),
    "read and edit use the same font": read.fontFamily === edit.fontFamily,
    "read and edit highlight the same way":
      JSON.stringify(read.distinctColors.sort()) === JSON.stringify(edit.distinctColors.sort()),
    "read mode has no language picker": read.hasPicker === false,
    "edit mode has one": edit.hasPicker === true,
    "both offer copy": read.hasCopy === true && edit.hasCopy === true,
    "copy puts the code on the clipboard":
      typeof clipboard === "string" && clipboard.includes("def greet(name):"),
    "the language picker changes the language": afterLanguage.language === "javascript",
    "typing inside the block reaches the document": /# typed/.test(saved || ""),
    "the fence keeps the language it was given": /```javascript/.test(saved || ""),
    "the code itself round-trips": /def greet\(name\):/.test(saved || "") && before.includes("def greet"),
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { read, edit, afterLanguage, clipboard, saved, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
