/**
 * Publish the documentation drafts to a Radd page space (RADD-1002).
 *
 * Reads a directory of markdown files that carry `title`, `parent` and `order`
 * frontmatter, builds the matching page tree under a root page, uploads every
 * referenced screenshot as an attachment on its own page, and rewrites the
 * markdown so the images and cross-links resolve.
 *
 * Idempotent on purpose. A documentation set is edited many times after it is
 * first published, and a publish step that forks the tree on the second run —
 * or uploads a second copy of every screenshot — makes the wiki worse each time
 * it is used. So a page is matched by slug under its parent and PATCHed, and an
 * attachment is matched by filename on the page and reused.
 *
 * This whole script is a REST fallback. The `radd` MCP server can read a page
 * and search pages, and cannot create or edit one; see RADD-1005.
 *
 * Usage:
 *   node scripts/publish-docs.mjs --root <dir> [--space radd]
 *                                 [--under "Radd Documentation"] [--dry-run]
 *                                 [--only user|dev]
 *
 * Reads the base URL from $RADD_DOCS_URL and the PAT from $RADD_API_TOKEN or
 * ~/.radd-token.
 */
import { readFile, readdir, stat } from "node:fs/promises";
import { resolve, dirname, basename, join } from "node:path";
import { homedir } from "node:os";

const argv = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[i + 1] : fallback;
};
const has = (name) => argv.includes(`--${name}`);

const ROOT = flag("root");
const SPACE_SLUG = flag("space", "radd");
const UNDER = flag("under", "Radd Documentation");
const ONLY = flag("only");
const DRY = has("dry-run");

if (!ROOT) {
  console.error('usage: publish-docs.mjs --root <dir> [--space radd] [--under "Radd Documentation"] [--dry-run] [--only user|dev]');
  process.exit(2);
}

const BASE = (process.env.RADD_DOCS_URL || "https://project.radd-hq.com").replace(/\/$/, "");
const TOKEN =
  process.env.RADD_API_TOKEN ||
  (await readFile(resolve(homedir(), ".radd-token"), "utf8").catch(() => "")).trim();
if (!TOKEN) {
  console.error("no PAT: set $RADD_API_TOKEN or create ~/.radd-token");
  process.exit(2);
}

const API = `${BASE}/api/v1`;

async function api(method, path, body) {
  const init = { method, headers: { Authorization: `Bearer ${TOKEN}` } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${method} ${path} -> ${response.status}: ${detail.slice(0, 400)}`);
  }
  return response.status === 204 ? null : response.json();
}

/** Multipart upload. Node 22 has FormData/Blob natively, so no dependency. */
async function uploadAttachment(pageId, filePath) {
  const form = new FormData();
  const bytes = await readFile(filePath);
  form.append("file", new Blob([bytes], { type: "image/png" }), basename(filePath));
  // The entity key is `page`. RADD-701 renamed it from `doc_page` and every
  // page upload 422'd for a day (RADD-761) — the value is worth stating.
  form.append("entity_type", "page");
  form.append("entity_id", pageId);
  const response = await fetch(`${API}/attachments`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}` },
    body: form,
  });
  if (!response.ok) {
    throw new Error(`upload ${basename(filePath)} -> ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  return response.json();
}

/** Frontmatter + body. Deliberately small — the format is three scalar keys. */
function parseDoc(text, file) {
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text);
  if (!match) throw new Error(`${file}: no frontmatter block`);
  const meta = {};
  for (const line of match[1].split("\n")) {
    const at = line.indexOf(":");
    if (at < 0) continue;
    const key = line.slice(0, at).trim();
    let value = line.slice(at + 1).trim();
    value = value.replace(/^["']|["']$/g, "");
    meta[key] = value;
  }
  if (!meta.title) throw new Error(`${file}: frontmatter has no title`);
  return { meta, body: text.slice(match[0].length).trim() };
}

const slugify = (title) =>
  title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 120);

/**
 * Find the file a markdown image reference means.
 *
 * Writers put their drafts in `<root>/user/` and `<root>/dev/` but their images
 * in `<root>/shots/<slice>/`, so `shots/u1/board.png` is relative to the ROOT
 * and not to the file that names it. Both readings are reasonable, and arguing
 * the point with every writer costs more than accepting both. The last resort
 * matches on filename alone, because a reference that is right about WHICH
 * image and wrong about where it sits is still unambiguous.
 */
async function locateImage(doc, url) {
  const candidates = [resolve(doc.dir, url), resolve(ROOT, url)];
  for (const candidate of candidates) {
    if (await stat(candidate).catch(() => null)) return candidate;
  }
  const wanted = basename(url);
  const shots = resolve(ROOT, "shots");
  if (await stat(shots).catch(() => null)) {
    for await (const found of walkAny(shots)) {
      if (basename(found) === wanted) return found;
    }
  }
  return null;
}

async function* walkAny(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walkAny(full);
    else yield full;
  }
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(full);
    else if (entry.name.endsWith(".md")) yield full;
  }
}

// --- gather the drafts -----------------------------------------------------

const files = [];
for (const sub of ONLY ? [ONLY] : ["user", "dev"]) {
  const dir = resolve(ROOT, sub);
  if (!(await stat(dir).catch(() => null))) continue;
  for await (const file of walk(dir)) files.push(file);
}
if (!files.length) {
  console.error(`no markdown found under ${ROOT}`);
  process.exit(1);
}

// `--match <regex>` publishes a subset, for reviewing one page before the bulk
// run. Include the container page in the pattern: a child whose parent is
// neither published nor drafted has nowhere to go.
const MATCH = flag("match");
const selected = MATCH ? files.filter((f) => new RegExp(MATCH).test(f)) : files;
if (MATCH) console.log(`--match ${MATCH}: ${selected.length} of ${files.length} file(s)`);

const docs = [];
for (const file of selected.sort()) {
  const { meta, body } = parseDoc(await readFile(file, "utf8"), file);
  docs.push({
    file,
    dir: dirname(file),
    title: meta.title,
    parent: meta.parent || UNDER,
    order: Number(meta.order ?? 0),
    slug: meta.slug || slugify(meta.title),
    body,
  });
}
console.log(`${docs.length} draft page(s) from ${ROOT}`);

// --- resolve the space and the existing tree -------------------------------

const spaces = await api("GET", "/page-spaces");
const space = spaces.find((s) => s.slug === SPACE_SLUG);
if (!space) throw new Error(`no page space with slug "${SPACE_SLUG}"`);

let existing = await api("GET", `/page-spaces/${space.id}/pages`);
const rootPage = existing.find((p) => p.title === UNDER && !p.parent_id)
  || existing.find((p) => p.title === UNDER);
if (!rootPage) throw new Error(`no page titled "${UNDER}" in space ${SPACE_SLUG}`);
console.log(`space ${space.name} (${space.slug}), root page "${rootPage.title}"`);

/** title -> page, for resolving a `parent` frontmatter value. */
const byTitle = new Map();
const indexExisting = () => {
  byTitle.clear();
  byTitle.set(rootPage.title, rootPage);
  for (const page of existing) byTitle.set(page.title, page);
};
indexExisting();

// Depth-first order, so a parent always exists before its children are made.
// A page whose parent is another draft page must wait for it.
const draftTitles = new Set(docs.map((d) => d.title));
const ordered = [];
const placed = new Set();
let guard = 0;
while (ordered.length < docs.length) {
  if (guard++ > docs.length + 5) {
    const stuck = docs.filter((d) => !placed.has(d.title)).map((d) => `${d.title} (parent: ${d.parent})`);
    throw new Error(`cannot order pages — a parent is missing or cyclic:\n  ${stuck.join("\n  ")}`);
  }
  for (const doc of docs) {
    if (placed.has(doc.title)) continue;
    const parentIsDraft = draftTitles.has(doc.parent);
    if (parentIsDraft && !placed.has(doc.parent)) continue;
    ordered.push(doc);
    placed.add(doc.title);
  }
}

// --- pass 1: every page exists ---------------------------------------------

const published = new Map(); // title -> { id, slug }

for (const doc of ordered) {
  const parent = byTitle.get(doc.parent);
  if (!parent) throw new Error(`${doc.file}: parent page "${doc.parent}" does not exist and is not a draft`);

  const siblings = existing.filter((p) => p.parent_id === parent.id);
  const match = siblings.find((p) => p.slug === doc.slug || p.title === doc.title);

  if (DRY) {
    console.log(`${match ? "update" : "create"}  ${doc.parent} / ${doc.title}  [${doc.slug}]`);
    published.set(doc.title, { id: match?.id ?? `dry-${doc.slug}`, slug: doc.slug });
    byTitle.set(doc.title, match ?? { id: `dry-${doc.slug}`, title: doc.title, slug: doc.slug });
    continue;
  }

  let page;
  if (match) {
    page = await api("PATCH", `/pages/${match.id}`, { title: doc.title, position: doc.order });
  } else {
    page = await api("POST", "/pages", {
      space_id: space.id,
      parent_id: parent.id,
      title: doc.title,
      slug: doc.slug,
      body: "",
      position: doc.order,
    });
    existing.push(page);
  }
  published.set(doc.title, { id: page.id, slug: page.slug });
  byTitle.set(doc.title, page);
  console.log(`${match ? "update" : "create"}  ${doc.parent} / ${doc.title}  [${page.slug}]`);
}

// --- pass 2: images and links, then the body -------------------------------

const IMAGE = /!\[([^\]]*)\]\(([^)]+)\)/g;
const WIKILINK = /\[\[([^\]]+)\]\]/g;

let uploads = 0;
let skipped = 0;

for (const doc of ordered) {
  const page = published.get(doc.title);
  let body = doc.body;

  // Images. A relative path is resolved against the draft file's directory,
  // which is what a writer means by `shots/u1/board.png`.
  const refs = [...body.matchAll(IMAGE)].filter(([, , url]) => !/^https?:|^\/api\//.test(url));
  if (refs.length && !DRY) {
    const already = await api("GET", `/attachments?entity_type=page&entity_id=${page.id}`);
    for (const [, , url] of refs) {
      const filePath = await locateImage(doc, url);
      if (!filePath) {
        console.log(`  MISSING image ${url}  (${doc.title})`);
        continue;
      }
      const name = basename(filePath);
      const prior = already.find((a) => a.filename === name);
      const attachment = prior ?? (await uploadAttachment(page.id, filePath));
      if (prior) skipped++;
      else uploads++;
      body = body.split(`](${url})`).join(`](/api/v1/attachments/${attachment.id})`);
    }
  } else if (refs.length && DRY) {
    for (const [, , url] of refs) {
      if (!(await locateImage(doc, url))) console.log(`  MISSING image ${url}  (${doc.title})`);
    }
  }

  // Cross-links. An unresolved [[Title]] is left as plain text rather than
  // turned into a broken link, and it is reported.
  body = body.replace(WIKILINK, (whole, title) => {
    const target = published.get(title.trim()) || byTitle.get(title.trim());
    if (!target || !target.slug) {
      console.log(`  UNRESOLVED link [[${title}]]  (${doc.title})`);
      return title;
    }
    return `[${title}](/pages/${space.slug}/${target.slug})`;
  });

  if (DRY) continue;
  await api("PATCH", `/pages/${page.id}`, { body });
}

console.log(
  DRY
    ? "\ndry run — nothing was written"
    : `\npublished ${ordered.length} page(s); uploaded ${uploads} image(s), reused ${skipped}`,
);
console.log(`${BASE}/pages/${space.slug}/${rootPage.slug}`);
