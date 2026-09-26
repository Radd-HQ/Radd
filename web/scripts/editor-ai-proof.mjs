/**
 * Browser proof for RADD-1395 against the REAL backend and the live chat provider: editor AI is
 * the ai plugin's, reached through the editor's extension points.
 *
 *   1. every AI control on the issue page is registered by the ai remote, loaded from /plugins/ai/;
 *   2. the rail card's Summarize answers in the host's reading pane;
 *   3. a rendered comment's read-menu Summarize produces text;
 *   4. a selection transform ("Fix grammar only") streams from the live provider into the host's
 *      per-block review, is accepted and saved, and the saved description reads back over the API;
 *   5. a portal form's draft shows the remote's Similar issues in the host's issue rows (typed,
 *      never submitted);
 *   6. no console errors; the throwaway issue is deleted at the end.
 *
 * Usage: node scripts/editor-ai-proof.mjs <baseUrl> [email] [password]
 *
 * It needs the chat provider to be reachable FROM THE SERVER. Where it is not (a sandbox with no
 * route to it), RADD_PROOF_STAND_IN_MODEL=1 answers the two AI streams in the browser so the rest —
 * the remote, the review, the save, the read-back, the cleanup — is still exercised against the
 * real backend; the report says which model answered. No provider or role is ever changed.
 */
import { resolve } from "node:path";
import { sleep, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const standIn = process.env.RADD_PROOF_STAND_IN_MODEL === "1";
const context = {};

/** The reading pane's answer once it is one: settled (not "Reading…"), long enough, and not an
 *  error — an unreachable provider renders its message in the same pane, which must not pass. */
const paneAnswer = (min) => `(() => {
  const body = document.querySelector("[data-reading-panel] .overflow-y-auto");
  const text = body?.innerText ?? "";
  if (!body || /^Reading|^Looking/.test(text)) return "";
  if (body.querySelector(".text-status-danger-ink, .text-red-400") || /AI provider|unreachable|unavailable|stream failed/i.test(text)) return "ERROR: " + text;
  return text.length > ${min} ? text : "";
})()`;

const ORIGINAL ="Teh first paragraph have sevral speling mistakes and it read badly.\n\nThe second paragraph is fine and should stay as it is.";
const COMMENT = "We shipped the fix on Tuesday. The regression came back after the cache flush on Wednesday, so we reverted the change and will retry next week after the database upgrade lands.";

const { session, close, check, finish, baseUrl } = await startProof({
  port: 9521, profile: resolve(process.env.TMPDIR || "/tmp", "radd-editor-ai-proof"),
});
const api = (method, path, body) => session.eval(`fetch("/api/v1${path}", {method: ${JSON.stringify(method)}, credentials: "include",
  headers: {"Content-Type": "application/json"}${body ? `, body: JSON.stringify(${JSON.stringify(body)})` : ""}})
  .then(async (r) => ({status: r.status, body: r.status === 204 ? null : await r.json().catch(() => null)}))`);
let itemId = null;
try {
  // Record what the page streams, to show the selection travelled with the run. With
  // RADD_PROOF_STAND_IN_MODEL=1 the page answers the two AI streams itself — for checking this
  // proof's own mechanics where the provider is out of reach; it is reported, and it is not the
  // live check this proof exists for.
  context.model = standIn ? "stand-in (answered in the browser)" : "live chat provider";
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__streams = [];
    const standIn = ${standIn};
    const original = window.fetch;
    const sse = (text) => new Response(new ReadableStream({ start(c) {
      const e = new TextEncoder();
      for (const t of text.match(/.{1,12}/gs)) c.enqueue(e.encode("data: " + JSON.stringify({t}) + "\\n\\n"));
      c.enqueue(e.encode("event: done\\ndata: {}\\n\\n")); c.close();
    } }), { headers: { "content-type": "text/event-stream" } });
    window.fetch = (input, init) => {
      // The api client passes a URL object, the streams a string: read either.
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/ai/editor/stream") && init && init.body) {
        const body = JSON.parse(init.body);
        window.__streams.push(body);
        if (standIn) return Promise.resolve(sse(body.action_id === "fix_grammar"
          ? "The first paragraph has several spelling mistakes and it reads badly."
          : "A stand-in summary: the fix shipped, regressed after a cache flush, and was reverted."));
      }
      if (standIn && url.includes("/ai/summarize/stream")) return Promise.resolve(sse("A stand-in digest of the whole issue, long enough to read as an answer."));
      return original(input, init);
    };` });

  const projects = await api("GET", "/projects?limit=5");
  const project = projects.body?.[0];
  const created = await api("POST", "/items", { project_id: project.id, title: "RADD-1395 editor AI proof (throwaway)", description: ORIGINAL });
  itemId = created.body?.id;
  check("a throwaway issue with a description", created.status === 201 || created.status === 200, `${created.status} in ${project?.key}`);
  const comment = await api("POST", `/items/${itemId}/comments`, { body: COMMENT });
  check("…and a comment on it", comment.status === 201 || comment.status === 200, String(comment.status));
  const key = created.body.key;
  context.issue = key;

  await session.navigate(`${baseUrl}/issues/${key}`, 500);
  // The composer's toolbar button appears once the whole editor-AI gate has loaded (status,
  // preferences AND the curated actions) — the read menu's Summarize waits on the same gate.
  await waitFor(session, `!!document.querySelector('[aria-label="AI actions for this comment"]') && !!document.querySelector("[data-ai-rail]")
    && !!document.querySelector('.radd-rich-editor [role="toolbar"] svg.radd-ai-toolbar-icon')`, { attempts: 120 });
  const loaded = await session.eval(`({
    remote: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/ai/")),
    owners: Object.fromEntries(["editor.toolbar.action", "editor.selection.action", "content.read.action", "issue.rail.top", "item.draft.assist"]
      .map((slot) => [slot, globalThis.__RADD_SLOT_REGISTRY__.forSlot(slot).map((e) => e.plugin)])),
    readMenus: document.querySelectorAll('[aria-label^="AI actions for"]').length,
  })`);
  check("the ai remote was loaded from /plugins/ai/", loaded.remote.some((n) => n.includes("/plugins/ai/remoteEntry.js")), loaded.remote.join(","));
  check("every editor, read-mode, rail and draft AI slot is contributed by the ai remote alone",
    Object.values(loaded.owners).every((o) => o.length === 1 && o[0] === "ai"), JSON.stringify(loaded.owners));
  check("the description and the comment each carry the remote's read menu", loaded.readMenus === 2, String(loaded.readMenus));

  // The rail card's Summarize: the whole issue, in the host's reading pane.
  await session.click("[data-ai-rail] button", (t) => t.trim() === "Summarize");
  const railSummary = await waitFor(session, paneAnswer(40), { attempts: 240 });
  check("the rail card's Summarize answers in the reading pane", railSummary && !String(railSummary).startsWith("ERROR"), String(railSummary).slice(0, 120));
  context.issueSummary = String(railSummary).slice(0, 200);
  check("the pane is labelled as the AI's answer", await session.eval(`document.querySelector("[data-reading-panel]")?.getAttribute("aria-label")`) === "AI results — Summary");
  await session.click('[data-reading-panel] button[aria-label^="Close"]');
  await waitFor(session, `!document.querySelector("[data-reading-panel]")`, { attempts: 20 });

  // A rendered comment's read menu.
  // The reading column re-centres as the pane closes; a click aimed mid-shift can miss, so aim
  // again rather than read a moved button as a missing menu.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await session.hover('[aria-label="AI actions for this comment"]');
    await session.click('[aria-label="AI actions for this comment"]');
    if (await waitFor(session, `!!document.querySelector("[data-ai-read-panel]")`, { attempts: 8 })) break;
  }
  check("a rendered comment's read menu opens", await session.eval(`!!document.querySelector("[data-ai-read-panel]")`));
  await session.click("[data-ai-read-panel] button", (t) => t.trim() === "Summarize");
  const commentSummary = await waitFor(session, paneAnswer(20), { attempts: 240 });
  check("a rendered comment's read-menu Summarize produces text", commentSummary && !String(commentSummary).startsWith("ERROR"), String(commentSummary).slice(0, 120));
  context.commentSummary = String(commentSummary).slice(0, 200);
  const summaryRequest = await session.eval(`window.__streams.at(-1)`);
  check("…streamed from the comment's own text", summaryRequest?.action_id === "summarize_selection" && summaryRequest?.document?.includes("cache flush"),
    JSON.stringify(summaryRequest)?.slice(0, 160));
  await session.click('[data-reading-panel] button[aria-label^="Close"]');

  // A selection transform on the description, reviewed and accepted.
  await session.hover(".group\\/desc");
  await session.click('[aria-label="Edit description"]');
  // The EDITABLE one: the read-only viewer shares `.radd-rich-editor` and can still be mounted for a
  // moment, and a selection inside it rightly gets no selection actions (a flake before this).
  const editable = `[...document.querySelectorAll(".radd-rich-editor:not(.radd-rich-viewer)")].find((e) => e.innerText.includes("sevral") && e.querySelector('.ProseMirror[contenteditable="true"]'))`;
  await waitFor(session, `!!${editable}`, { attempts: 40 });
  await session.eval(`${editable}.setAttribute("data-proof-desc", "")`);
  const selected = await session.eval(`(() => {
    const pm = document.querySelector("[data-proof-desc] .ProseMirror"); pm.focus();
    const text = pm.querySelector("p").firstChild; const range = document.createRange();
    range.setStart(text, 0); range.setEnd(text, text.length);
    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); return selection.toString();
  })()`);
  const button = await waitFor(session, `!!document.querySelector("[data-editor-selection-actions] [data-ai-selection-button]")`, { attempts: 40 });
  check("Ask AI appears over the selection, placed by the editor", button, selected);
  await session.click("[data-ai-selection-button]");
  await waitFor(session, `!!document.querySelector("[data-ai-selection-menu]")`, { attempts: 20 });
  await session.click("[data-ai-selection-menu] button", (t) => t.trim() === "Fix grammar only");
  const streaming = await waitFor(session, `!!document.querySelector("[data-proof-desc] [data-editor-run-panel]")`, { attempts: 40, every: 100 });
  check("the run band opens in the editor's chrome", streaming);
  const reviewing = await waitFor(session, `(() => {
    const band = document.querySelector("[data-proof-desc] [data-editor-run-panel]");
    return band && /to review/.test(band.innerText) ? document.querySelectorAll("[data-proof-desc] .milkdown-diff-controls").length : 0;
  })()`, { attempts: 240 });
  check("the live provider's reply lands in the host's per-block review", reviewing > 0,
    `${reviewing} pair(s); band: ${await session.eval(`document.querySelector("[data-proof-desc] [data-editor-run-panel]")?.innerText ?? "(closed)"`)}; ` +
    `page says: ${await session.eval(`[...document.querySelectorAll("[role=status], [role=alert]")].map((e) => e.innerText).join(" / ")`)}`);
  const sent = await session.eval(`window.__streams.at(-1)`);
  check("the captured selection travelled with the run", sent?.action_id === "fix_grammar" && sent?.selection?.includes("sevral"),
    JSON.stringify({ action: sent?.action_id, selection: sent?.selection })?.slice(0, 160));
  await session.click("[data-proof-desc] [data-editor-run-panel] button", (t) => /accept all/i.test(t));
  await waitFor(session, `!document.querySelector("[data-proof-desc] [data-editor-run-panel]")`, { attempts: 20 });
  const edited = await session.eval(`document.querySelector("[data-proof-desc] .ProseMirror").innerText`);
  check("Accept all applies the correction in the editor", !edited.includes("sevral") && edited.includes("second paragraph"), edited.slice(0, 160));
  await sleep(500);
  await session.click("button", (t) => t.trim() === "Save");
  await waitFor(session, `!document.querySelector("[data-proof-desc]")`, { attempts: 40 });
  const read = await waitFor(session, `fetch("/api/v1/items/${itemId}", {credentials: "include"}).then((r) => r.json())
    .then((item) => item.description !== ${JSON.stringify(ORIGINAL)} ? item.description : "")`, { attempts: 20 });
  check("the saved description reads back over the API, corrected, with the untouched paragraph intact",
    read && !read.includes("sevral") && read.includes("The second paragraph is fine"), String(read).slice(0, 200));
  context.savedDescription = String(read).slice(0, 200);

  // The submission form's assist panel: "Similar issues" beside a draft is the remote's too
  // (item.draft.assist). Typed, never submitted.
  const portal = await api("GET", "/portal/forms");
  const form = portal.body?.flatMap?.((group) => group.forms)[0];
  if (form) {
    await session.navigate(`${baseUrl}/portal/forms/${form.id}`, 500);
    await waitFor(session, `!!document.querySelector("form input:not([type=hidden]):not([type=checkbox])")`, { attempts: 40 });
    await session.click("form input:not([type=hidden]):not([type=checkbox])");
    await session.send("Input.insertText", { text: "Render farm crash when submitting comp jobs" });
    const similar = await waitFor(session, `document.querySelectorAll("[data-ai-draft-similar] li a[href^='/issues/']").length`, { attempts: 80 });
    check("the submission form's Similar issues come from the remote, as the host's issue rows", similar > 0, `${similar} row(s) on ${form.name}`);
  } else {
    check("a portal form to exercise the draft assist on", false, "none on this instance");
  }

  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} catch (error) {
  check("the proof ran to its end", false, String(error?.message ?? error).split("\n")[0]);
  context.openMenus = await session.eval(`[...document.querySelectorAll("[data-ai-read-panel]")].map((e) => e.innerText)`).catch(() => null);
  context.gates = await session.eval(`(() => {
    const q = window.__RADD_QUERY_CLIENT__;
    const state = (key) => { const s = q.getQueryState(key); return s && { status: s.status, fetch: s.fetchStatus, data: JSON.stringify(q.getQueryData(key))?.slice(0, 80), error: String(s.error ?? "") }; };
    return { me: state(["radd-sdk", "me"]), status: state(["ai", "status"]), prefs: state(["ai", "preferences"]), actions: state(["ai", "editor-actions"]) };
  })()`).catch(() => null);
} finally {
  if (itemId) {
    const removed = await api("DELETE", `/items/${itemId}`).catch((error) => ({ status: String(error) }));
    const gone = await api("GET", `/items/${itemId}`).catch(() => ({ status: 0 }));
    check("the throwaway issue is deleted", (removed.status === 204 || removed.status === 200) && gone.status === 404, `${removed.status}/${gone.status}`);
  }
  await close();
}
finish({ proof: "editor AI (RADD-1395)", ...context });
