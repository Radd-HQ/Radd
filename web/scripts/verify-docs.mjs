/**
 * Check that published documentation pages actually rendered (RADD-1002).
 *
 * Publishing reports success when the API accepted the body. That is not the
 * same as the reader seeing a document: RADD-1006 renders a page with prose,
 * code and images intact and NO headings at all, and nothing anywhere reports
 * an error. A publish pipeline with no render check ships that silently.
 *
 * So this compares what each draft SAYS it contains against what the live page
 * actually produces: heading count, and whether every image resolved.
 *
 * usage: node scripts/verify-docs.mjs --root <dir> [--space radd] [--port N]
 */
import { readFile, readdir } from "node:fs/promises";
import { resolve, join } from "node:path";
import { homedir } from "node:os";
import { openDocsBrowser, goto } from "./lib/docshot.mjs";

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : fallback;
};
const ROOT = flag("root");
const SPACE = flag("space", "radd");
const PORT = Number(flag("port", "9530"));
if (!ROOT) {
  console.error("usage: verify-docs.mjs --root <dir> [--space radd] [--port N]");
  process.exit(2);
}

const token =
  process.env.RADD_API_TOKEN ||
  (await readFile(resolve(homedir(), ".radd-token"), "utf8").catch(() => "")).trim();

const slugify = (t) =>
  t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 120);

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.name.endsWith(".md")) yield full;
  }
}

/** Headings in the SOURCE, ignoring anything inside a fenced block — the whole
 *  point is to compare against what the author actually wrote. */
function sourceHeadings(body) {
  const out = [];
  let fenced = false;
  for (const line of body.split("\n")) {
    if (/^\s{0,3}(`{3,}|~{3,})/.test(line)) { fenced = !fenced; continue; }
    if (fenced) continue;
    const m = /^(#{1,3})\s+(.*)$/.exec(line);
    if (m) out.push(m[2].trim());
  }
  return out;
}

const drafts = [];
for (const sub of ["user", "dev"]) {
  const dir = resolve(ROOT, sub);
  try {
    for await (const file of walk(dir)) {
      const text = await readFile(file, "utf8");
      const fm = /^---\n([\s\S]*?)\n---\n?/.exec(text);
      if (!fm) continue;
      const meta = Object.fromEntries(
        fm[1].split("\n").filter((l) => l.includes(":")).map((l) => {
          const at = l.indexOf(":");
          return [l.slice(0, at).trim(), l.slice(at + 1).trim().replace(/^["']|["']$/g, "")];
        }),
      );
      const body = text.slice(fm[0].length);
      drafts.push({ title: meta.title, slug: meta.slug || slugify(meta.title), headings: sourceHeadings(body) });
    }
  } catch { /* directory absent */ }
}

const { session, close } = await openDocsBrowser({
  port: PORT,
  profile: resolve("/tmp", `radd-verifydocs-${PORT}`),
  baseUrl: process.env.RADD_DOCS_URL || "https://project.radd-hq.com",
  token,
});

const problems = [];
try {
  for (const draft of drafts) {
    let line;
    try {
      await goto(session, `/pages/${SPACE}/${draft.slug}`, { waitFor: "[data-page-body]" });
      // Wait for the async render to settle; see RADD-1006.
      let last = -1, stable = 0;
      for (let i = 0; i < 80 && stable < 4; i++) {
        const n = await session.eval(
          `document.querySelectorAll("[data-page-body] h1,[data-page-body] h2,[data-page-body] h3,[data-page-body] p,[data-page-body] pre,[data-page-body] .cm-editor").length`,
        );
        stable = n === last && n > 0 ? stable + 1 : 0;
        last = n;
        await new Promise((r) => setTimeout(r, 250));
      }
      const seen = await session.eval(
        `(() => {
          const b = document.querySelector("[data-page-body]");
          if (!b) return null;
          const imgs = [...b.querySelectorAll("img")];
          return {
            headings: b.querySelectorAll("h1,h2,h3").length,
            images: imgs.length,
            brokenImages: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
          };
        })()`,
      );
      const want = draft.headings.length;
      const ok = seen && seen.headings >= want && seen.brokenImages === 0;
      line = `${ok ? "ok  " : "FAIL"}  ${draft.slug}  headings ${seen?.headings ?? "?"}/${want}` +
        `  images ${seen?.images ?? 0}${seen?.brokenImages ? ` (${seen.brokenImages} BROKEN)` : ""}`;
      if (!ok) problems.push(draft.slug);
    } catch (error) {
      line = `FAIL  ${draft.slug}  ${error.message}`;
      problems.push(draft.slug);
    }
    console.log(line);
  }
} finally {
  close();
}

console.log(
  problems.length
    ? `\n${problems.length} page(s) did not render as written: ${problems.join(", ")}`
    : `\nall ${drafts.length} page(s) rendered as written`,
);
process.exit(problems.length ? 1 : 0);
