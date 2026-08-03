/**
 * The editor's rendered typography, measured (RADD-754).
 *
 * This exists because "the editor looks the same in both themes" is not a thing
 * you can check by eye, and the change it guards — replacing Crepe's stylesheets
 * with our own — moves every one of these values or none of them.
 *
 * Two modes:
 *
 *   --save <file>   record the current appearance as a baseline
 *   (default)       measure again and report what MOVED
 *
 * A baseline is a record of what shipped, not of what is correct. When a value
 * changes deliberately, the diff is the thing to read and then re-save.
 *
 * Usage: node scripts/editor-style-proof.mjs <baseUrl> <spaceSlug> <email> <password> [--save <file>]
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const args = process.argv.slice(2);
const saveAt = args.indexOf("--save");
const savePath = saveAt >= 0 ? args[saveAt + 1] : null;
const [baseUrl, spaceSlug, email, password] = args.filter((a) => !a.startsWith("--") && a !== savePath);
const PORT = 9459;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-editor-style-proof");
const BASELINE = resolve(process.cwd(), "scripts/editor-style-baseline.json");

/** Content that exercises every block and inline shape the editor renders. */
const SEED = [
  "# Heading one",
  "",
  "## Heading two",
  "",
  "### Heading three",
  "",
  "A paragraph with **bold**, *italic*, ~~strike~~, `code` and a [link](https://example.com).",
  "",
  "- a bullet",
  "- another bullet",
  "",
  "1. first",
  "2. second",
  "",
  "> a quotation",
  "",
  "```python",
  "x = 1",
  "```",
  "",
  "| A | B |",
  "| --- | --- |",
  "| 1 | 2 |",
  "",
  "---",
  "",
].join("\n");

/** The properties that decide whether text looks the same. */
const PROPS = [
  "fontFamily", "fontSize", "fontWeight", "fontStyle", "lineHeight",
  "color", "backgroundColor", "textDecorationLine",
  "marginTop", "marginBottom", "paddingLeft", "paddingTop",
  "borderLeftWidth", "borderLeftColor", "borderBottomWidth", "borderRadius",
];

const TARGETS = {
  editor: ".ProseMirror",
  h1: ".ProseMirror h1",
  h2: ".ProseMirror h2",
  h3: ".ProseMirror h3",
  p: ".ProseMirror p",
  strong: ".ProseMirror strong",
  em: ".ProseMirror em",
  del: ".ProseMirror del",
  inlineCode: ".ProseMirror code",
  link: ".ProseMirror a",
  ul: ".ProseMirror ul",
  li: ".ProseMirror li",
  ol: ".ProseMirror ol",
  blockquote: ".ProseMirror blockquote",
  table: ".ProseMirror table",
  th: ".ProseMirror th",
  td: ".ProseMirror td",
  hr: ".ProseMirror hr",
  codeBlock: "[data-code-block]",
};

const MEASURE = `((targets, props) => {
  const out = {};
  for (const [name, selector] of Object.entries(targets)) {
    const el = document.querySelector(selector);
    if (!el) { out[name] = null; continue; }
    const s = getComputedStyle(el);
    const row = {};
    for (const p of props) row[p] = s[p];
    const r = el.getBoundingClientRect();
    row._width = Math.round(r.width);
    out[name] = row;
  }
  return out;
})(${JSON.stringify(TARGETS)}, ${JSON.stringify(PROPS)})`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1200 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "style-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Style proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3500);

  const measured = {};
  for (const theme of ["dark", "light"]) {
    await session.eval(`(() => {
      document.documentElement.classList.toggle("light", ${theme === "light"});
    })()`);
    await sleep(400);
    measured[theme] = await session.eval(MEASURE);
  }

  const missing = Object.entries(measured.dark)
    .filter(([, value]) => value === null)
    .map(([name]) => name);

  if (savePath || !existsSync(BASELINE)) {
    const target = savePath ?? BASELINE;
    writeFileSync(target, JSON.stringify(measured, null, 2) + "\n");
    console.log(`baseline written to ${target}`);
    console.log(`missing elements: ${missing.length ? missing.join(", ") : "none"}`);
    return missing.length ? 1 : 0;
  }

  const baseline = JSON.parse(readFileSync(BASELINE, "utf8"));
  const moved = [];
  for (const theme of ["dark", "light"]) {
    for (const [name, row] of Object.entries(baseline[theme] ?? {})) {
      const now = measured[theme]?.[name];
      if (!row) continue;
      if (!now) { moved.push(`${theme}.${name}: GONE`); continue; }
      for (const [prop, was] of Object.entries(row)) {
        if (now[prop] !== was) moved.push(`${theme}.${name}.${prop}: ${was} -> ${now[prop]}`);
      }
    }
  }

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "every element the baseline recorded still renders": !moved.some((m) => m.endsWith("GONE")),
    "nothing about the editor's appearance moved": moved.length === 0,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { moved: moved.slice(0, 60), movedCount: moved.length, missing, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
