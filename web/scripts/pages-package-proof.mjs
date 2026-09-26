/**
 * Browser proof for RADD-1392 against the REAL backend: the wiki is the pages plugin's bundled
 * package, and it still works end to end.
 *
 *   1. the pages index and a space render (the space found through the index's own search);
 *   2. a page renders — its body, a `radd:toc` block through the SDK's extension registry, the
 *      discussion and the inline-comment rail — and the tree and the sidebar's Pages section show it;
 *   3. it edits and saves through the host editor bridge (a live room's Done, or the single-editor
 *      Save), and the new body reads back over the API;
 *   4. the print view renders the page and asks to print;
 *   5. Settings → Page spaces (the plugin's settings page) lists the space;
 *   6. no chunk the host loads eagerly carries a wiki component: distinctive strings live only in
 *      lazily loaded chunks, named after the package's modules, fetched when the wiki is opened;
 *   7. no console errors.
 *
 * It creates a throwaway space and page and deletes both, whatever happens.
 *
 * Usage: node scripts/pages-package-proof.mjs <baseUrl> [email] [password]
 */
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { sleep, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const web = fileURLToPath(new URL("..", import.meta.url));

/** Strings only a wiki component renders — never the sidebar section, which is eager by design. */
const WIKI_STRINGS = ["Joining the page…", "Pages below this one", "Rebuild link index", "Export as PDF, with subpages", "Passage removed"];

const api = (session, method, path, body) => session.eval(`fetch("/api/v1${path}", {method: ${JSON.stringify(method)},
  credentials: "include", headers: {"Content-Type": "application/json"}${body ? `, body: ${JSON.stringify(JSON.stringify(body))}` : ""}})
  .then(async (r) => ({status: r.status, body: r.status === 204 ? null : await r.json().catch(() => null)}))`);

/** Type into a search box the way a person does, so React sees the change. */
const search = (session, placeholder, text) => session.eval(`(() => {
  const el = document.querySelector(${JSON.stringify(`input[placeholder="${placeholder}"]`)});
  if (!el) return false;
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, ${JSON.stringify(text)});
  el.dispatchEvent(new Event("input", {bubbles: true}));
  return true;
})()`);

const stamp = Date.now().toString(36);
const spaceName = `RADD-1392 proof ${stamp}`;
const marker = `edited-${stamp}`;
let space = null;
let page = null;
const { session, close, check, finish, baseUrl } = await startProof({
  port: 9512, profile: resolve(process.env.TMPDIR || "/tmp", "radd-pages-package-proof"),
});
try {
  // window.print() would block headless Chrome; count the calls instead.
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.__printed = 0; window.print = () => { window.__printed += 1; };" });
  const caps = await session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  check("pages is enabled and ships no remote (it is bundled)",
    caps.plugins.includes("pages") && !(caps.remotes ?? []).some((r) => r.name === "pages"), JSON.stringify(caps.remotes?.map((r) => r.name)));

  const createdSpace = await api(session, "POST", "/page-spaces", { name: spaceName, description: "Throwaway space for the RADD-1392 proof." });
  space = createdSpace.body;
  check("created a throwaway space", createdSpace.status === 201, JSON.stringify(createdSpace));
  const createdPage = await api(session, "POST", "/pages", {
    space_id: space.id, title: "Package proof page",
    body: "```radd:toc\n```\n\n## Heading one\n\nOriginal body text for the proof.\n",
  });
  page = createdPage.body;
  check("created a throwaway page", createdPage.status === 201, JSON.stringify(createdPage).slice(0, 200));

  // 6 (runtime half): the landing page loads none of the wiki's chunks.
  await session.navigate(`${baseUrl}/`, 1500);
  const chunksAtHome = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name.split("/").pop())`);

  // 1. The index, with the space found through its own search.
  await session.navigate(`${baseUrl}/pages`, 600);
  await waitFor(session, `document.querySelector("h1")?.textContent === "Pages" && !!document.querySelector('input[placeholder="Find spaces by name or slug…"]')`);
  await search(session, "Find spaces by name or slug…", spaceName);
  const listed = await waitFor(session, `[...document.querySelectorAll('ul[aria-label="Page spaces"] a')].some((a) => a.textContent.includes(${JSON.stringify(spaceName)}))`);
  check("the pages index renders and finds the space", listed);

  // 1. The space: its header and tree.
  await session.navigate(`${baseUrl}/pages/${space.slug}`, 600);
  const inTree = await waitFor(session, `[...document.querySelectorAll('nav[aria-label="Page tree"] a')].some((a) => a.textContent.includes("Package proof page"))`);
  check("the space renders and its tree shows the page", inTree);
  check("the space's empty state asks for a page", await session.eval(`document.body.innerText.includes("Select a page from the tree.")`));

  // 2. The page.
  await session.navigate(`${baseUrl}/pages/${space.slug}/${page.path}`, 600);
  const rendered = await waitFor(session, `document.querySelector("[data-page-body]")?.textContent.includes("Original body text for the proof.")`);
  check("the page body renders through the host viewer", rendered);
  check("the title is the page's", await session.eval(`document.querySelector('input[aria-label="Page title"]')?.value === "Package proof page"`));
  const toc = await waitFor(session, `(() => { const b = document.querySelector('[data-extension="toc"]'); return b && b.textContent.includes("On this page") && b.textContent.includes("Heading one"); })()`);
  check("a radd:toc block renders through the SDK's extension registry", toc);
  check("the discussion and the inline-comment rail render",
    await waitFor(session, `!!document.querySelector("[data-page-discussion]") && !!document.querySelector("[data-inline-comment-rail]")`));
  const sidebar = await waitFor(session, `[...document.querySelectorAll("aside a")].some((a) => a.getAttribute("href") === ${JSON.stringify(`/pages/${space.slug}`)})`);
  check("the sidebar's Pages section (the plugin's slot) links the space", sidebar);
  const chunksOnPage = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name.split("/").pop())`);

  // 3. Edit and save.
  await session.click('button[aria-label="Edit page"]');
  const editor = await waitFor(session, `!!document.querySelector('[aria-label="Edit page content"] .ProseMirror[contenteditable="true"]')`);
  check("Edit opens the host editor through the bridge", editor);
  await waitFor(session, `[...document.querySelectorAll('[aria-label="Edit page content"] .ProseMirror p')].some((p) => p.textContent.includes("Original body text"))`);
  await session.click('[aria-label="Edit page content"] .ProseMirror p', (text) => text.includes("Original body text"));
  await session.send("Input.insertText", { text: ` ${marker} ` });
  const flow = await waitFor(session, `(() => {
    const buttons = [...document.querySelectorAll('[aria-label="Edit page content"] button')];
    const done = buttons.find((b) => b.textContent.trim() === "Done" && !b.disabled);
    const save = buttons.find((b) => b.textContent.trim() === "Save" && !b.disabled);
    return done ? "live room" : save ? "single editor" : "";
  })()`, { attempts: 150 });
  check("the editor offers its finish control (a live room's Done, or Save)", flow,
    await session.eval(`document.querySelector('[aria-label="Edit page content"]')?.innerText.slice(0, 200)`));
  await sleep(600); // the editor reports its markdown on its own tick
  // The matcher runs in the page, so the label travels as a literal.
  const finish = flow === "live room" ? "Done" : "Save";
  if (flow) await session.click('[aria-label="Edit page content"] button', new Function("text", `return text.trim() === ${JSON.stringify(finish)}`));
  let saved = null;
  for (let i = 0; i < 40 && !saved?.body?.body?.includes(marker); i += 1) {
    await sleep(250);
    saved = await api(session, "GET", `/pages/${page.id}`);
  }
  check(`the edit saves (${flow || "no save control"}) and reads back over the API`, saved?.body?.body?.includes(marker), saved?.body?.body?.slice(0, 160));
  check("the page leaves edit mode and shows the saved body",
    await waitFor(session, `!document.querySelector('[aria-label="Edit page content"]') && document.querySelector("[data-page-body]")?.textContent.includes(${JSON.stringify(marker)})`));

  // 4. The print view.
  await session.navigate(`${baseUrl}/print/pages/${space.slug}/${page.path}`, 600);
  const printed = await waitFor(session, `window.__printed > 0 && document.querySelector(".radd-print")?.textContent.includes(${JSON.stringify(marker)})`);
  check("the print view renders the page and asks to print", printed);
  check("the print view carries no app shell", await session.eval(`!document.querySelector("aside")`));

  // 5. Settings → Page spaces.
  await session.navigate(`${baseUrl}/settings/pages`, 600);
  await waitFor(session, `!!document.querySelector('input[placeholder="Find spaces by name or slug…"]')`);
  await search(session, "Find spaces by name or slug…", spaceName);
  const managed = await waitFor(session, `[...document.querySelectorAll('ul[aria-label="Manage page spaces"] li')].some((li) => li.textContent.includes(${JSON.stringify(spaceName)}))`);
  check("Settings → Page spaces (the plugin's settings page) lists the space", managed);

  // 6. Build output: which chunks carry the wiki, and whether the host loads any of them eagerly.
  const html = await session.eval(`fetch("/").then((r) => r.text())`);
  const eager = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
  const assets = resolve(web, "dist/assets");
  const chunks = readdirSync(assets).filter((f) => f.endsWith(".js"));
  const carrying = Object.fromEntries(WIKI_STRINGS.map((s) => [s, chunks.filter((f) => readFileSync(resolve(assets, f), "utf8").includes(s))]));
  check("each wiki string lives in exactly one chunk", Object.values(carrying).every((list) => list.length === 1), JSON.stringify(carrying));
  check("no chunk the host loads eagerly carries a wiki component",
    eager.length > 0 && Object.values(carrying).flat().every((f) => !eager.includes(f)), JSON.stringify({ eager: eager.length, carrying }));
  const wikiChunks = [...new Set(Object.values(carrying).flat())];
  check("the wiki's chunks are the package's modules (PageSpacePage, PageBody, SpacesSettingsPage)",
    wikiChunks.every((f) => /^(PageSpacePage|PageBody|SpacesSettingsPage)-/.test(f)), wikiChunks.join(", "));
  check("the landing page fetched none of them; the page route fetched the page's",
    wikiChunks.every((f) => !chunksAtHome.includes(f)) && chunksOnPage.some((f) => f.startsWith("PageSpacePage-")),
    JSON.stringify({ home: chunksAtHome.filter((f) => wikiChunks.includes(f)), page: chunksOnPage.filter((f) => wikiChunks.includes(f)) }));
  check("the host source holds no wiki components", !existsSync(resolve(web, "src/components/pages")) && !existsSync(resolve(web, "src/routes/page-space.tsx")));

  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} finally {
  // Clean up every row created, whatever failed above.
  if (page) {
    const gone = await api(session, "DELETE", `/pages/${page.id}?hard=true`);
    check("the throwaway page is deleted", gone.status === 204, JSON.stringify(gone));
  }
  if (space) {
    const gone = await api(session, "DELETE", `/page-spaces/${space.id}?force=true`);
    const after = await api(session, "GET", `/page-spaces/by-identity/${space.id}`);
    check("the throwaway space is deleted", gone.status === 204 && after.status === 404, `${gone.status} / ${after.status}`);
  }
  await close();
}
finish({ proof: "pages package" });
