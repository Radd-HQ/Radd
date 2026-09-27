/**
 * RADD-1283 against a running Radd: resolvable threads in a page's Discussion,
 * and a project's who-may-resolve rule reaching what a reader is told.
 *
 * Page: the composer is a Comment / Start thread row until asked for (RADD-1448); Start thread
 * opens it in Thread mode with one submit (lit only with text) that makes a marked thread; Resolve
 * marks it "Resolved by …"; Reply on the collapsed thread opens it with the composer; a plain reply
 * keeps it resolved and closes the composer; Reply and unresolve reopens it; the Unresolved filter
 * hides an ordinary comment.
 *
 * Rule: on a fresh project, a member-scoped key (item.read + comment.write, no
 * project.manage) reads its OWN thread as resolvable under the default, and as
 * not resolvable once the project says "managers"; the server refuses that
 * resolve too — the read and the write give the same answer.
 *
 *   node scripts/page-threads-proof.mjs [baseUrl] [email] [password]
 */
import { mkdir } from "node:fs/promises";
import { report, waitFor } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-page-threads-proof";

/** Type into a just-mounted editor; retry until `lit` holds (a fresh Milkdown can
 *  take focus before its listener is attached, dropping the first keystrokes). */
async function typeInto(session, editorSelector, text, lit) {
  // The rich editor is lazy-loaded: on a real instance its chunk can land after the composer's
  // buttons do, so wait for the editable before clicking it.
  await waitFor(session, `!!document.querySelector(${JSON.stringify(editorSelector)})`, { attempts: 40 });
  for (let attempt = 0; attempt < 5; attempt++) {
    await session.click(editorSelector);
    await session.send("Input.insertText", { text });
    if (await waitFor(session, lit, { attempts: 6 })) return true;
  }
  return false;
}

async function main() {
  await mkdir(output, { recursive: true });
  const { session, close, baseUrl, loginStatus } = await startProof({
    port: 9537, profile: output + "/chrome", width: 1440, height: 1100,
  });
  const checks = { loggedIn: loginStatus === 204 };
  const api = (expression) => session.eval(`(async () => { ${expression} })()`);
  const D = "[data-page-discussion]";
  const card = (id) => `document.querySelector('${D} [data-comment-id="${id}"]')`;
  let context = {};
  try {
    // --- the page Discussion ---------------------------------------------------
    const page = await api(`
      const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
      const page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: spaces[0].id, title: "Page threads proof " + Date.now().toString(36), body: "A page to discuss." }),
      })).json();
      await fetch("/api/v1/page/" + page.id + "/comments", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: "Just a note" }),
      });
      return { id: page.id, slug: page.slug, space: spaces[0].slug };`);
    await session.navigate(`${baseUrl}/pages/${page.space}/${page.slug}`, 2500);
    checks.discussionLoaded = await waitFor(session, `!!document.querySelector('${D} [data-start-thread]')`);
    checks.composerHiddenUntilAsked = await session.eval(`(() => {
      const row = document.querySelector('${D} [data-comment-composer="closed"]');
      return !!row && [...row.querySelectorAll("button")].map((b) => b.textContent.trim()).join("|") === "Comment|Start thread"
        && !document.querySelector('${D} [data-comment-composer] [contenteditable="true"]');
    })()`);
    await session.click(`${D} [data-start-thread]`);
    const submit = `document.querySelector('${D} [data-comment-composer="open"] button[type="submit"]')`;
    checks.startThreadDarkWhenEmpty = await waitFor(session, `${submit}?.textContent.trim() === "Start thread" && ${submit}.disabled
      && document.querySelectorAll('${D} [data-comment-composer="open"] button[type="submit"]').length === 1`);
    checks.startThreadLightsWithText = await typeInto(session, `${D} [data-comment-composer="open"] [contenteditable="true"]`, "Is this page still accurate?",
      `!${submit}.disabled`);
    await session.click(`${D} [data-comment-composer="open"] button[type="submit"]`);
    checks.threadMarked = await waitFor(session, `[...document.querySelectorAll('${D} [data-thread="unresolved"]')].some(li => li.textContent.includes("still accurate"))
      && [...document.querySelectorAll('${D} [data-thread-state]')].some(chip => chip.textContent.trim() === "Unresolved thread")`);
    const threadId = await session.eval(`[...document.querySelectorAll('${D} [data-thread]')].find(li => li.textContent.includes("still accurate"))?.dataset.commentId`);
    checks.ordinaryUnmarked = await session.eval(`(() => { const li = [...document.querySelectorAll('${D} li[data-comment-id]')].find(el => el.textContent.includes("Just a note")); return !!li && !li.dataset.thread; })()`);

    await session.click(`${D} [data-thread-resolution="${threadId}"]`);
    checks.resolvedBy = await waitFor(session, `${card(threadId)}?.dataset.thread === "resolved"
      && ${card(threadId)}.querySelector('[data-thread-state]').textContent.includes("Resolved by")`);
    await session.screenshot(output + "/resolved.png");

    // Resolved, the thread folds its replies away; Reply opens them with the composer in one click.
    await session.click(`${D} [data-open-reply="${threadId}"]`);
    const replyEditor = `${D} [data-comment-replies="${threadId}"] [contenteditable="true"]`;
    checks.replyComposerOnResolved = await waitFor(session, `!!document.querySelector('${replyEditor}') && !!document.querySelector('${D} [data-reply-unresolve]')`);
    await typeInto(session, replyEditor, "Checked the first half.",
      `!document.querySelector('${D} [data-reply-unresolve]').disabled`);
    await session.click(`${D} [data-comment-replies="${threadId}"] button[type="submit"]`);
    // The composer closing is what says the post landed; until then its own text would match.
    checks.postingClosesTheReplyComposer = await waitFor(session, `!document.querySelector('${D} [data-reply-composer]')`);
    checks.plainReplyKeepsResolved = await waitFor(session, `${card(threadId)}?.querySelector('[data-comment-replies]')?.textContent.includes("Checked the first half.")`)
      && await session.eval(`${card(threadId)}.dataset.thread === "resolved"`);
    await session.click(`${D} [data-open-reply="${threadId}"]`);
    await waitFor(session, `!!document.querySelector('${replyEditor}')`);
    await typeInto(session, replyEditor, "The second half is out of date.",
      `!document.querySelector('${D} [data-reply-unresolve]').disabled`);
    await session.click(`${D} [data-reply-unresolve]`);
    checks.replyAndUnresolveReopens = await waitFor(session, `${card(threadId)}?.dataset.thread === "unresolved"
      && ${card(threadId)}.textContent.includes("The second half is out of date.")`);

    await session.click(`${D} [data-comment-filter="unresolved"]`);
    checks.unresolvedFilter = await waitFor(session, `!![...document.querySelectorAll('${D} li[data-comment-id]')].length
      && [...document.querySelectorAll('${D} li[data-comment-id]')].every(li => li.dataset.thread === "unresolved")`);
    await session.screenshot(output + "/filter.png");
    await session.click(`${D} [data-comment-filter="all"]`);

    // --- the project rule reaches the reader ------------------------------------
    context = await api(`
      const json = (r) => r.json();
      const call = (method, path, body, headers = {}) => fetch("/api/v1" + path, {
        method, credentials: headers.Authorization ? "omit" : "include",
        headers: {"Content-Type": "application/json", ...headers}, body: body ? JSON.stringify(body) : undefined });
      const project = await json(await call("POST", "/projects", { key: "PT" + Math.random().toString(36).slice(2, 6).toUpperCase(), name: "Page threads proof" }));
      const item = await json(await call("POST", "/items", { project_id: project.id, title: "Rule check" }));
      const token = await json(await call("POST", "/tokens", { name: "page-threads-proof member", scopes: { global: ["item.read", "comment.write"] } }));
      const member = { Authorization: "Bearer " + token.token };
      const thread = await json(await call("POST", "/items/" + item.id + "/comments", { body: "Mine to close?", is_thread: true }, member));
      const canResolve = async () => (await json(await call("GET", "/items/" + item.id + "/comments/feed", null, member))).comments.find(c => c.id === thread.id).can_resolve;
      const byDefault = await canResolve();
      const put = await call("PUT", "/projects/" + project.id + "/thread-resolution", { default: "managers", overrides: [] });
      const policy = await json(await call("GET", "/projects/" + project.id + "/thread-resolution"));
      const underManagers = await canResolve();
      const refused = (await call("POST", "/comments/" + thread.id + "/resolve", {}, member)).status;
      const audit = await json(await call("GET", "/audit?entity_type=thread_resolution_policy&limit=5"));
      await call("DELETE", "/tokens/" + token.id);
      await call("DELETE", "/projects/" + project.id + "?confirm=" + encodeURIComponent(project.key));
      return { byDefault, putStatus: put.status, policy, underManagers, refused,
        audited: JSON.stringify(audit).includes("thread_resolution_policy") };`);
    checks.memberResolvesOwnByDefault = context.byDefault === true;
    checks.policySaved = context.putStatus === 200 && context.policy.default === "managers";
    checks.managersRuleHidesIt = context.underManagers === false;
    checks.serverAgreesAndRefuses = context.refused === 403;
    checks.policyChangeAudited = context.audited;
  } finally {
    await close();
  }
  process.exit(report(checks, context) ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
