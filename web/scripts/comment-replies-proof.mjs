#!/usr/bin/env node
/**
 * Proof for threaded replies on every comment surface (RADD-1246):
 *
 *   node web/scripts/comment-replies-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 *   1. an issue comment takes a reply from the page (RADD-1448: a comment with no replies shows no
 *      disclosure, only a Reply action; one click opens the composer; posting closes it onto the
 *      reply, and the disclosure then counts it);
 *   2. under a PUBLIC issue comment the reply form offers "Internal reply";
 *      posting one lands with the internal marking;
 *   3. under an INTERNAL issue comment the form is locked to internal and
 *      the server refuses a public reply (409) — measured over the API;
 *   4. a page's general discussion comment takes a reply too;
 *   5. a scoped key without comment.read_internal lists only the public
 *      reply and counts one — the audience is the reader's, not the root's.
 * Fixtures are deleted at the end.
 */
import { resolve } from "node:path";
import { outputPath, PAGE_API, report, sleep, waitForSelector } from "./lib/cdp.mjs";
import { startProof } from "./lib/proof.mjs";

const PORT = 9498;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-comment-replies-proof");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `CR${STAMP.slice(-4).toUpperCase()}`;
const SLUG = `replies-proof-${STAMP}`;

async function main() {
  const { session, close, baseUrl, loginStatus } = await startProof({ port: PORT, profile: PROFILE, width: 1500, height: 1000 });
  const checks = {};
  const context = { key: KEY, slug: SLUG, login: loginStatus };
  let projectId = null;
  let spaceId = null;
  try {
    const setup = await session.eval(`(async () => { ${PAGE_API}
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Replies proof" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "Threaded issue" });
      const publicRoot = await api("POST", "/items/" + item.body.id + "/comments", { body: "A public question" });
      const internalRoot = await api("POST", "/items/" + item.body.id + "/comments", { body: "An internal note", visibility: "internal" });
      const space = await api("POST", "/page-spaces", { name: "Replies proof", slug: ${JSON.stringify(SLUG)} });
      const page = await api("POST", "/pages", { space_id: space.body.id, title: "Discussed", body: "Some text to discuss." });
      const discussion = await api("POST", "/page/" + page.body.id + "/comments", { body: "General remark" });
      return { project: project.body, item: item.body, publicRoot: publicRoot.body, internalRoot: internalRoot.body, space: space.body, page: page.body, discussion: discussion.body };
    })()`);
    projectId = setup.project.id;
    spaceId = setup.space.id;
    context.setup = { item: setup.item.key, publicRoot: setup.publicRoot?.id, internalRoot: setup.internalRoot?.id, discussion: setup.discussion?.id };

    // RADD-1448: Reply is the comment footer's action; one click opens the composer, and posting
    // closes it — so every reply starts from the button.
    const openComposer = async (rootId) => {
      await waitForSelector(session, `[data-open-reply="${rootId}"]`);
      if (!(await session.eval(`!!document.querySelector('[data-comment-replies="${rootId}"] [data-reply-composer]')`))) {
        await session.click(`[data-open-reply="${rootId}"]`);
      }
      await waitForSelector(session, `[data-comment-replies="${rootId}"] [data-reply-composer]`);
    };
    // What a comment nobody has answered offers: a Reply action, and no disclosure over nothing.
    const footerOf = (rootId) => session.eval(`({
      toggle: document.querySelector('[data-thread-toggle="${rootId}"]')?.textContent?.trim() ?? null,
      reply: document.querySelector('[data-open-reply="${rootId}"]')?.textContent?.trim() ?? null,
    })`);
    // --- 1 + 2: a reply, then an INTERNAL reply, under a public issue comment ----
    await session.navigate(`${baseUrl}/issues/${setup.item.key}`, 2500);
    await waitForSelector(session, `[data-open-reply="${setup.publicRoot.id}"]`);
    const footerBefore = await footerOf(setup.publicRoot.id);
    await openComposer(setup.publicRoot.id);
    const form = await session.eval(`(() => {
      const box = document.querySelector('[data-comment-replies="${setup.publicRoot.id}"]');
      return box ? { present: true, internalSwitch: Boolean(box.querySelector("[data-reply-internal]")), locked: Boolean(box.querySelector('[data-reply-audience="locked"]')) } : { present: false };
    })()`);
    context.publicForm = { footerBefore, ...form };
    checks.aCommentWithoutRepliesOffersReplyAndNoDisclosure = footerBefore.toggle === null && footerBefore.reply === "Reply";
    checks.publicThreadOffersAnInternalSwitch = form.present && form.internalSwitch && !form.locked;
    // The reply composer is the rich editor: focus its document, then type.
    const typeReply = async (rootId, text) => {
      await openComposer(rootId);
      // A posted reply renders through a read-only ProseMirror as well, so the
      // composer's editor must be addressed by its own wrapper, never "the
      // first .ProseMirror in the box".
      await waitForSelector(session, `[data-comment-replies="${rootId}"] [data-reply-composer] .ProseMirror`);
      await session.click(`[data-comment-replies="${rootId}"] [data-reply-composer] .ProseMirror`, () => true);
      await session.send("Input.insertText", { text });
      // The editor reports its markdown on its own tick; the Reply button
      // enabling is the signal the draft has reached React state.
      await waitForSelector(session, `[data-comment-replies="${rootId}"] button[type="submit"]:not([disabled])`);
    };
    // Parity with the top-level composer: same editor, same affordances (the
    // AI toolbar icon is the marker the render proofs already use). The top-level
    // composer is hidden until asked for (RADD-1448), so open it for the comparison.
    await openComposer(setup.publicRoot.id);
    await waitForSelector(session, `[data-comment-replies="${setup.publicRoot.id}"] [data-reply-composer] .ProseMirror`);
    await session.click("[data-open-comment]");
    await waitForSelector(session, '[data-comment-composer="open"] .ProseMirror');
    await sleep(300);
    const parity = await session.eval(`(() => {
      const reply = document.querySelector('[data-comment-replies="${setup.publicRoot.id}"] [data-reply-composer]');
      const main = document.querySelector('[data-comment-composer="open"]');
      return {
        replyEditor: Boolean(reply?.querySelector(".ProseMirror")),
        replyAi: Boolean(reply?.querySelector(".radd-ai-toolbar-icon")),
        mainAi: Boolean(main?.querySelector(".radd-ai-toolbar-icon")),
      };
    })()`);
    context.parity = parity;
    checks.replyComposerIsTheRichEditorWithTheSameAiToolbar = parity.replyEditor && parity.replyAi === parity.mainAi;
    await session.click("[data-composer-cancel]");
    await typeReply(setup.publicRoot.id, "Answering in public");
    await session.click(`[data-comment-replies="${setup.publicRoot.id}"] button[type="submit"]`, () => true);
    // Posting closes the composer onto the new reply, with the disclosure now counting it.
    await waitForSelector(session, `[data-comment-replies="${setup.publicRoot.id}"] [data-reply-visibility="public"]`);
    await sleep(500);
    const afterPost = await session.eval(`({
      composer: Boolean(document.querySelector('[data-comment-replies="${setup.publicRoot.id}"] [data-reply-composer]')),
      toggle: document.querySelector('[data-thread-toggle="${setup.publicRoot.id}"]')?.textContent?.trim() ?? null,
    })`);
    context.afterPost = afterPost;
    checks.postingClosesTheComposerOntoTheReply = afterPost.composer === false && afterPost.toggle === "Hide 1 reply";
    await openComposer(setup.publicRoot.id);
    await session.eval(`document.querySelector('[data-comment-replies="${setup.publicRoot.id}"] [data-reply-internal] [data-option="internal"]').click()`);
    await sleep(200);
    await typeReply(setup.publicRoot.id, "Staff-only aside");
    const submitLabel = await session.eval(`document.querySelector('[data-comment-replies="${setup.publicRoot.id}"] button[type="submit"]')?.textContent?.trim()`);
    await session.click(`[data-comment-replies="${setup.publicRoot.id}"] button[type="submit"]`, () => true);
    // The list refetches after the post; poll for the second row rather than
    // trusting a fixed delay (the rich editor's remount shares the same tick).
    await waitForSelector(session, `[data-comment-replies="${setup.publicRoot.id}"] [data-reply-visibility="internal"]`);
    const replies = await session.eval(`[...document.querySelectorAll('[data-comment-replies="${setup.publicRoot.id}"] [data-reply-visibility]')].map((n) => [n.getAttribute("data-reply-visibility"), n.textContent.includes("Internal")])`);
    context.publicReplies = { submitLabel, replies };
    checks.publicAndInternalRepliesLandUnderThePublicThread =
      submitLabel === "Reply internally" && replies.length === 2 && replies[0][0] === "public" && replies[1][0] === "internal" && replies[1][1] === true;
    await session.screenshot(outputPath("comment-replies-proof-issue.png"));

    // --- 3: the internal thread is locked, and the server refuses a public reply ---
    await openComposer(setup.internalRoot.id);
    const locked = await session.eval(`(() => {
      const box = document.querySelector('[data-comment-replies="${setup.internalRoot.id}"]');
      return box ? { locked: Boolean(box.querySelector('[data-reply-audience="locked"]')), internalSwitch: Boolean(box.querySelector("[data-reply-internal]")), label: box.querySelector('button[type="submit"]')?.textContent?.trim() } : null;
    })()`);
    const refused = await session.eval(`(async () => { ${PAGE_API}
      const pub = await api("POST", "/comments/${setup.internalRoot.id}/replies", { body: "leak", visibility: "public" });
      const ok = await api("POST", "/comments/${setup.internalRoot.id}/replies", { body: "inherits internal" });
      return { pub: pub.status, ok: ok.status, okVisibility: ok.body?.visibility };
    })()`);
    context.internalThread = { locked, refused };
    checks.internalThreadLocksRepliesToInternal = locked?.locked === true && locked.internalSwitch === false && locked.label === "Reply internally";
    checks.serverRefusesAPublicReplyUnderAnInternalThread = refused.pub === 409 && refused.ok === 201 && refused.okVisibility === "internal";

    // --- 5: a reader without comment.read_internal sees one reply, counts one ----
    // A SECOND account, not a scoped key of the admin's: the internal reply's
    // author always sees their own comment, so the reader must be someone else.
    // The project goes public with contributions, which is what gives a
    // signed-in member item.read + comment.write and nothing internal.
    const colleague = await session.eval(`(async () => { ${PAGE_API}
      const me = await api("GET", "/auth/me");
      const user = await api("POST", "/users", { email: "replies-proof-${STAMP}@example.com", name: "Proof Colleague", password: "change-me-too" });
      const access = await api("PUT", "/projects/${projectId}/public-access", { public: true, contributions: true });
      return { me: me.body?.user?.id ?? me.body?.id, user: user.body, userStatus: user.status, access: access.status };
    })()`);
    context.colleague = { userStatus: colleague.userStatus, access: colleague.access };
    const login = await fetch(`${baseUrl}/api/v1/auth/login`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: `replies-proof-${STAMP}@example.com`, password: "change-me-too" }),
    });
    const cookie = (login.headers.get("set-cookie") ?? "").split(";")[0];
    const asColleague = async (path) => {
      const r = await fetch(`${baseUrl}/api/v1${path}`, { headers: { cookie } });
      return { status: r.status, body: await r.json().catch(() => null) };
    };
    const page = await asColleague(`/comments/${setup.publicRoot.id}/replies`);
    const feed = await asColleague(`/items/${setup.item.id}/comments`);
    const scoped = { login: login.status, replies: (page.body?.comments ?? []).map((c) => c.visibility), counts: (feed.body ?? []).map((c) => [c.visibility, c.reply_count]) };
    context.scoped = scoped;
    checks.aReaderWithoutTheAtomSeesOnlyThePublicReply =
      (scoped.login === 200 || scoped.login === 204) && scoped.replies.join() === "public" && JSON.stringify(scoped.counts) === JSON.stringify([["public", 1]]);
    await session.eval(`(async () => { ${PAGE_API} await api("DELETE", "/users/${colleague.user?.id}?reassign_to=${colleague.me}"); })()`).catch(() => null);

    // --- 4: a page discussion comment takes a reply ----------------------------
    await session.navigate(`${baseUrl}/pages/${SLUG}/${setup.page.path}`, 2500);
    await waitForSelector(session, `[data-open-reply="${setup.discussion.id}"]`);
    const pageFooter = await footerOf(setup.discussion.id);
    await typeReply(setup.discussion.id, "Discussion reply");
    // Read while the composer is open: posting closes it, which would make "no switch" vacuous.
    const pageInternalSwitch = await session.eval(`Boolean(document.querySelector('[data-comment-replies="${setup.discussion.id}"] [data-reply-internal]'))`);
    await session.click(`[data-comment-replies="${setup.discussion.id}"] button[type="submit"]`, () => true);
    await waitForSelector(session, `[data-comment-replies="${setup.discussion.id}"] [data-reply-visibility]`);
    await sleep(500);
    const pageReplies = await session.eval(`({
      replies: [...document.querySelectorAll('[data-comment-replies="${setup.discussion.id}"] [data-reply-visibility]')].length,
      internalSwitch: ${pageInternalSwitch},
    })`);
    context.page = { pageFooter, ...pageReplies };
    checks.pageDiscussionTakesAPublicReply = pageFooter.toggle === null && pageFooter.reply === "Reply"
      && pageReplies.replies === 1 && pageReplies.internalSwitch === false;
    await session.screenshot(outputPath("comment-replies-proof-page.png"));
  } finally {
    await session.eval(`(async () => { ${PAGE_API}
      ${spaceId ? `await api("DELETE", "/page-spaces/${spaceId}?force=true");` : ""}
      ${projectId ? `await api("DELETE", "/projects/${projectId}");` : ""}
    })()`).catch(() => null);
    await close();
  }
  report(checks, context);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
