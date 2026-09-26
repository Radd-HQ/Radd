#!/usr/bin/env node
/**
 * Browser proof for RADD-1397 against the REAL backend: co-editing's UI is the collab plugin's.
 *
 *   node web/scripts/collab-plugin-proof.mjs <baseUrl> [email] [password]
 *
 * Two browsers, one account, one throwaway page (created here, deleted at the end):
 *   1. both open the page to edit and are bound to one live document; what each types converges;
 *   2. the collab code arrived from /plugins/collab/ (the entry, the transport chunk with yjs, the
 *      binding chunk) and the binding ran on the host's shared ProseMirror shims — while NO host
 *      chunk either browser loaded carries yjs, y-websocket or y-prosemirror (checked by content);
 *   3. exactly one browser is the elected saver, and the body it persisted — read back over the
 *      API — holds both lines, after the autosave and after Done;
 *   4. no console errors in either browser.
 */
import { resolve } from "node:path";
import { openBrowser, PAGE_API, report, sleep, waitFor } from "./lib/cdp.mjs";
import { proofArgs } from "./lib/proof.mjs";

const { baseUrl, email, password } = proofArgs();
const STAMP = Date.now().toString(36).slice(-6);
const SEED = `A throwaway page for the collab plugin proof ${STAMP}.`;
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });
const context = {};

const EDITOR = `document.querySelector('[aria-label="Edit page content"] .ProseMirror')`;
const EDITOR_TEXT = `(${EDITOR}?.innerText ?? "")`;
const SAVER = `(document.querySelector("[data-collab-saver]")?.getAttribute("data-collab-saver") ?? "absent")`;
/** Content signatures, not file names: what only these libraries (or this feature) contain. */
const SIGNATURES = {
  yjs: "Yjs was already imported",
  "y-websocket": "connection-close",
  "y-prosemirror": "\"y-sync\"",
  collab: "/collab/pages",
};

/** The login endpoint throttles bursts: retry until it lets us in. */
async function signIn(session) {
  await session.navigate(`${baseUrl}/login`, 800);
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const status = await session.login(baseUrl, email, password);
    if (status === 200 || status === 204) return status;
    await sleep(4000);
  }
  return 0;
}

async function typeAtEnd(session, text) {
  await session.eval(`(() => {
    const view = ${EDITOR}; view.focus();
    const range = document.createRange(); range.selectNodeContents(view); range.collapse(false);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
  })()`);
  await session.send("Input.insertText", { text });
}

/** Every script the page loaded, and which carry each signature. */
async function loadedScripts(session) {
  return session.eval(`(async () => {
    const urls = [...new Set(performance.getEntriesByType("resource").map((e) => e.name)
      .filter((u) => new URL(u).origin === location.origin && u.split("?")[0].endsWith(".js")))];
    const signatures = ${JSON.stringify(SIGNATURES)};
    const out = [];
    for (const url of urls) {
      const text = await (await fetch(url, { cache: "no-store" })).text();
      out.push({ path: new URL(url).pathname, carries: Object.keys(signatures).filter((k) => text.includes(signatures[k])) });
    }
    return out;
  })()`);
}

const one = await openBrowser({ port: 9517, profile: resolve(process.env.TMPDIR || "/tmp", "radd-collab-plugin-proof-one"), width: 1400, height: 950 });
const two = await openBrowser({ port: 9518, profile: resolve(process.env.TMPDIR || "/tmp", "radd-collab-plugin-proof-two"), width: 1400, height: 950 });
let created = null;
try {
  check("browser one signed in", [200, 204].includes(await signIn(one.session)));
  check("browser two signed in", [200, 204].includes(await signIn(two.session)));
  check("the browser reports a hover-capable pointer", await one.session.eval(`matchMedia("(hover: hover)").matches`));
  const caps = await one.session.eval(`fetch("/api/v1/capabilities").then((r) => r.json())`);
  const remote = caps.remotes.find((r) => r.name === "collab");
  check("collab is enabled and declares its remote at UI API 1.17.0",
    remote?.remote_entry.startsWith("/plugins/collab/remoteEntry.js") && remote.ui_api_version === "1.17.0", JSON.stringify(remote));

  created = await one.session.eval(`(async () => { ${PAGE_API}
    const space = (await api("POST", "/page-spaces", { name: "Collab plugin proof ${STAMP}", slug: "collab-plugin-${STAMP}" })).body;
    const page = (await api("POST", "/pages", { space_id: space.id, title: "Shared ${STAMP}", body: ${JSON.stringify(SEED)} })).body;
    return { space: { id: space.id, slug: space.slug }, page: { id: page.id, slug: page.slug, path: page.path } };
  })()`);
  context.created = created;
  check("a throwaway space and page exist", created?.space?.id && created?.page?.id, JSON.stringify(created));
  const pageUrl = `${baseUrl}/pages/${created.space.slug}/${created.page.path ?? created.page.slug}`;

  for (const browser of [one, two]) {
    await browser.session.navigate(pageUrl, 1500);
    await waitFor(browser.session, `document.body.innerText.includes(${JSON.stringify(SEED)})`);
    await browser.session.click("button", (text) => text.trim() === "Edit page");
    await waitFor(browser.session, `${EDITOR}?.getAttribute("contenteditable") === "true"`);
  }
  const bound = await Promise.all([one, two].map((b) => b.session.eval(`({
    editable: ${EDITOR}?.getAttribute("contenteditable"),
    seeded: (${EDITOR_TEXT}.match(/${SEED.slice(0, 20)}/g) || []).length,
    bar: document.querySelector('[aria-label="Edit page content"] .radd-rich-editor')?.innerText ?? "",
    buttons: [...document.querySelectorAll('[aria-label="Edit page content"] button')].map((b) => b.textContent.trim()),
  })`)));
  context.bound = bound;
  check("both editors are bound to the room: seeded once, 'Editing together', Done instead of Save",
    bound.every((b) => b.editable === "true" && b.seeded === 1 && /Editing together/.test(b.bar)
      && b.buttons.includes("Done") && !b.buttons.includes("Save")), JSON.stringify(bound));

  await sleep(1500);
  const election = { one: await one.session.eval(SAVER), two: await two.session.eval(SAVER) };
  context.election = election;
  check("exactly one browser is the elected saver", [election.one, election.two].filter((v) => v === "true").length === 1
    && [election.one, election.two].filter((v) => v === "false").length === 1, JSON.stringify(election));
  const saver = election.one === "true" ? one : two;
  const other = saver === one ? two : one;

  // The saver types first, then the other — the order in which the saver must save a colleague's line.
  const saverLine = ` The saver's line ${STAMP}.`;
  const otherLine = ` The other line ${STAMP}.`;
  await typeAtEnd(saver.session, saverLine);
  check("the saver's line reaches the other browser",
    await waitFor(other.session, `${EDITOR_TEXT}.includes(${JSON.stringify(saverLine.trim())})`));
  await typeAtEnd(other.session, otherLine);
  check("the other line reaches the saver",
    await waitFor(saver.session, `${EDITOR_TEXT}.includes(${JSON.stringify(otherLine.trim())})`));
  await sleep(500);
  const texts = await Promise.all([one, two].map((b) => b.session.eval(EDITOR_TEXT)));
  context.texts = texts;
  check("the two documents converge", texts[0] === texts[1] && texts[0].includes(saverLine.trim()) && texts[0].includes(otherLine.trim()));

  const persisted = await waitFor(one.session, `(async () => { ${PAGE_API}
    const body = (await api("GET", "/pages/${created.page.id}")).body.body;
    return body.includes(${JSON.stringify(saverLine.trim())}) && body.includes(${JSON.stringify(otherLine.trim())}) ? body : "";
  })()`, { attempts: 24, every: 500 });
  context.autosaved = persisted;
  check("the elected saver's autosave persisted both lines (read back over the API)", Boolean(persisted));

  // What each browser loaded, by content.
  const scripts = [...await loadedScripts(one.session), ...await loadedScripts(two.session)];
  const byPath = new Map(scripts.map((s) => [s.path, s.carries]));
  const plugin = [...byPath].filter(([p]) => p.startsWith("/plugins/collab/"));
  const host = [...byPath].filter(([p]) => p.startsWith("/assets/"));
  context.pluginChunks = Object.fromEntries(plugin);
  context.hostChunksLoaded = host.length;
  check("the collab entry, transport and binding chunks loaded from /plugins/collab/",
    ["remoteEntry.js", "room.js", "bind-editor.js"].every((f) => plugin.some(([p]) => p === `/plugins/collab/${f}`)), JSON.stringify(plugin.map(([p]) => p)));
  check("yjs, y-websocket and y-prosemirror arrived in the plugin's chunks (the scan sees them)",
    plugin.some(([, c]) => c.includes("yjs")) && plugin.some(([, c]) => c.includes("y-websocket")) && plugin.some(([, c]) => c.includes("y-prosemirror")),
    JSON.stringify(Object.fromEntries(plugin)));
  check("the binding ran on the host's shared ProseMirror (the lazy shims loaded)",
    ["model", "state", "view"].every((m) => byPath.has(`/shared/prosemirror-${m}.js`)));
  const carriers = host.filter(([, c]) => c.some((k) => k !== "collab"));
  check(`none of the ${host.length} host chunks loaded carries yjs, y-websocket or y-prosemirror`,
    host.length > 20 && carriers.length === 0, JSON.stringify(carriers));

  // Done: the saver's final save; the body stays whole.
  await other.session.click("button", (text) => text.trim() === "Done");
  await sleep(1200);
  await saver.session.click("button", (text) => text.trim() === "Done");
  await waitFor(saver.session, `!document.querySelector('[aria-label="Edit page content"]')`);
  await sleep(1500);
  const after = await one.session.eval(`(async () => { ${PAGE_API}
    return (await api("GET", "/pages/${created.page.id}")).body; })()`);
  context.final = { version: after.version, body: after.body };
  check("after Done the persisted body holds the seed and both lines",
    [SEED, saverLine.trim(), otherLine.trim()].every((line) => after.body.includes(line)), after.body);

  const errors = { one: one.session.consoleErrors, two: two.session.consoleErrors };
  context.consoleErrors = errors;
  check("no console errors", errors.one.length === 0 && errors.two.length === 0, JSON.stringify(errors).slice(0, 400));
} finally {
  if (created?.page?.id) {
    const cleanup = await one.session.eval(`(async () => { ${PAGE_API}
      const page = (await api("DELETE", "/pages/${created.page.id}?hard=true")).status;
      const space = (await api("DELETE", "/page-spaces/${created.space.id}?force=true")).status;
      const gone = (await api("GET", "/pages/${created.page.id}")).status;
      return { page, space, gone };
    })()`).catch((error) => ({ error: String(error) }));
    context.cleanup = cleanup;
    check("the throwaway page and space are deleted", cleanup.page === 204 && cleanup.space === 204 && cleanup.gone === 404, JSON.stringify(cleanup));
  }
  await Promise.all([one.close(), two.close()]);
}
const failed = report(checks, context);
process.exit(failed ? 1 : 0);
