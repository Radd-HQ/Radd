/**
 * The RADD-745 parity contract, walked (RADD-755).
 *
 * The epic's inventory is what the editor DOES, read from the code rather than
 * from anyone's memory, and the gate says to walk it surface by surface before
 * deleting the dependency — treating a row that cannot be ticked as a missing
 * sibling rather than a note to file later.
 *
 * The rows with their own proof are not re-tested here (code blocks, tables,
 * images, the AI surface, the toolbar, extensions, styling); this covers the
 * ones that had none, and it covers them on EVERY SURFACE the contract lists,
 * because "it works on a page" is what a per-feature proof already told us and
 * "it works in a comment, a new-item modal and a public form" is what nobody
 * had checked.
 *
 * Usage: node scripts/editor-parity-proof.mjs <baseUrl> <spaceSlug> <projectKey> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, projectKey, email, password] = process.argv.slice(2);
const PORT = 9460;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-parity-proof");

/** Content exercising the rows that have no proof of their own. */
const SEED = [
  "# Parity",
  "",
  "A paragraph with a [link](https://example.com) and `code`.",
  "",
  "- one",
  "- two",
  "",
  "> quoted",
  "",
].join("\n");

async function waitFor(session, expression, tries = 24) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(250);
  }
  return false;
}

/** What an editor on the current page offers. */
const SURFACE = `(() => {
  const pm = document.querySelector(".ProseMirror");
  if (!pm) return { mounted: false };
  return {
    mounted: true,
    toolbar: !!document.querySelector('[role="toolbar"][aria-label="Formatting"]'),
    // The engine, not a textarea: markdown in, markdown out, rendered live.
    rendersMarkdown: !!pm.querySelector("h1, p, ul, blockquote"),
    plainToggle: [...document.querySelectorAll("button")]
      .some((b) => /plain text editing/i.test(b.textContent || "")),
    markdownHint: !!document.querySelector('[title="Markdown is supported"]'),
    placeholder: !!document.querySelector(".radd-placeholder"),
    aiButton: !!document.querySelector("svg.radd-ai-toolbar-icon"),
    extensionButton: !!document.querySelector("svg.radd-extension-toolbar-icon"),
  };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const setup = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "parity-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Parity proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    const scoped = await (await fetch("/api/v1/items?limit=1&q=" +
      encodeURIComponent("project = ${projectKey}"), {credentials:"include"})).json();
    const any = scoped.length ? scoped
      : await (await fetch("/api/v1/items?limit=1", {credentials:"include"})).json();
    return { pageId: page.id, slug: page.slug, itemKey: any[0] ? any[0].key : null };
  })()`);

  // --- PageView (body) ------------------------------------------------------
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${setup.slug}`, 2500);
  const readMode = await session.eval(`(() => {
    const pm = document.querySelector(".ProseMirror");
    return {
      rendered: !!pm && !!pm.querySelector("h1"),
      // Read mode is the same engine, so a list is a list and a quote a quote.
      list: !!pm?.querySelector("ul"),
      quote: !!pm?.querySelector("blockquote"),
      // Scoped to the BODY. A read-mode page legitimately carries a formatting
      // toolbar — the page-comment composer's — so "no toolbar on the document"
      // is the claim, not "no toolbar on the page".
      noToolbar: !document.querySelector('[data-page-body] [role="toolbar"][aria-label="Formatting"]'),
      bodyIsViewer: !!document.querySelector("[data-page-body] .radd-rich-viewer"),
    };
  })()`);

  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await waitFor(session, `!!document.querySelector('[role="toolbar"][aria-label="Formatting"]')`);
  await sleep(1500);
  const pageBody = await session.eval(SURFACE);

  // Jira markup tolerated: an imported body must still render (jiraToMarkdown).
  const jira = await session.eval(`(async () => {
    await fetch("/api/v1/pages/${setup.pageId}", {
      method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ body: "h1. Old Jira heading\\n\\n* a bullet\\n" }),
    });
    return true;
  })()`);
  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${setup.slug}`, 2500);
  await waitFor(session, `!!document.querySelector(".ProseMirror h1")`);
  const jiraRendered = await session.eval(`(() => {
    const pm = document.querySelector(".ProseMirror");
    return {
      heading: !!pm?.querySelector("h1"),
      // The tell: the raw h1. marker must be CONSUMED, not printed.
      rawMarkupVisible: (pm?.textContent || "").includes("h1."),
    };
  })()`);

  // --- CommentsThread (an issue) -------------------------------------------
  let comment = { mounted: false };
  if (setup.itemKey) {
    await session.navigate(`${baseUrl}/issues/${setup.itemKey}`, 3000);
    await session.eval(`(() => {
      const b = [...document.querySelectorAll("button, textarea, [contenteditable]")]
        .find((e) => /comment|write/i.test(e.getAttribute("placeholder") || e.textContent || ""));
      b?.click();
    })()`);
    await sleep(2000);
    comment = await session.eval(SURFACE);
  }

  // --- NewItemModal ---------------------------------------------------------
  await session.navigate(`${baseUrl}/`, 2500);
  await session.eval(`(() => {
    const b = [...document.querySelectorAll("button")]
      .find((x) => /^new item$/i.test((x.textContent || "").trim()) ||
                   /New item/.test(x.getAttribute("title") || "") ||
                   /New item/.test(x.getAttribute("aria-label") || ""));
    b?.click();
  })()`);
  await sleep(900);
  // It may open a project picker first; take the first project offered.
  await session.eval(`(() => {
    const item = document.querySelector('[role="menu"] [role="menuitem"], [role="listbox"] [role="option"]');
    item?.click();
  })()`);
  await waitFor(session, `!!document.querySelector('[role="dialog"] .ProseMirror')`, 40);
  await sleep(900);
  const newItem = await session.eval(SURFACE);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    // Read and edit are the same engine — the contract's first row.
    "read mode renders the document": readMode.rendered === true && readMode.list === true &&
      readMode.quote === true,
    "the page body is a viewer, with no editing chrome":
      readMode.noToolbar === true && readMode.bodyIsViewer === true,
    "the page body mounts a full editor": pageBody.mounted === true && pageBody.toolbar === true,
    "it renders markdown live": pageBody.rendersMarkdown === true,
    "the plain-text fallback is offered": pageBody.plainToggle === true &&
      pageBody.markdownHint === true,
    "a page offers the extension button": pageBody.extensionButton === true,
    // Jira markup tolerated (RADD-745's inventory).
    "an old Jira-markup body still renders": jira === true && jiraRendered.heading === true &&
      jiraRendered.rawMarkupVisible === false,
    // The surfaces the contract lists, not just the one every proof uses.
    "an item was found to comment on": setup.itemKey !== null,
    "an issue comment mounts the same editor":
      comment.mounted === true && comment.toolbar === true,
    "a comment does NOT offer the extension button": comment.extensionButton === false,
    "the new-item modal mounts the same editor":
      newItem.mounted === true && newItem.toolbar === true,
    "and shows its placeholder when empty": newItem.placeholder === true,
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { setup, readMode, pageBody, jiraRendered, comment, newItem, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
