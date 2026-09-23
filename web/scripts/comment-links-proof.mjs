#!/usr/bin/env node
/**
 * Proof for RADD-1297 (GitHub radd-hq/radd#23): a link to one comment lands
 * on that comment.
 *
 *   node web/scripts/comment-links-proof.mjs http://127.0.0.1:8000 admin@example.com change-me
 *
 *   1. `?comment=` on an issue lands on a comment OLDER than the first page
 *      (130 comments; the target is the 126th newest) — in view and ringed;
 *   2. a link to a REPLY opens its thread and lands on the reply;
 *   3. Copy link puts the canonical `/issues/KEY?comment=` address on the
 *      clipboard;
 *   4. a comment id nobody can see opens the issue as usual — no error, no hint;
 *   5. a wiki page's permalink carries `?comment=` through its redirect and
 *      lands on the discussion comment;
 *   6. a real notification (a colleague @-mentions you in a comment) opens
 *      from the Inbox ON that comment.
 * Fixtures (project, space, colleague) are deleted at the end.
 */
import { resolve } from "node:path";
import { clickAt, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, adminEmail, adminPassword] = process.argv.slice(2);
if (!baseUrl || !adminEmail || !adminPassword) {
  console.error("usage: comment-links-proof.mjs <baseUrl> <adminEmail> <adminPassword>");
  process.exit(2);
}
const PORT = 9500;
const TMP = process.env.TMPDIR || "/tmp";
const PROFILE = resolve(TMP, "radd-comment-links-proof");
const SHOTS = resolve(TMP, "radd-comment-links-proof-shots");
const STAMP = Date.now().toString(36).slice(-5);
const KEY = `CL${STAMP.slice(-4).toUpperCase()}`;
const COLLEAGUE = `colleague-${STAMP}@example.test`;
const PASSWORD = "comment-links-pass-1";

const API = `
  const api = async (method, path, body) => {
    const r = await fetch("/api/v1" + path, {
      method, headers: { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await r.text();
    return { status: r.status, body: text ? JSON.parse(text) : null };
  };
`;

/** Where one comment row is: present, in the viewport, highlighted. */
const landing = (id) => `(() => {
  const row = document.querySelector('[data-comment-id="${id}"]');
  if (!row) return { present: false };
  const r = row.getBoundingClientRect();
  return { present: true, inView: r.top >= 0 && r.bottom <= innerHeight, ringed: row.hasAttribute("data-comment-linked") };
})()`;

async function waitFor(session, expression, timeoutMs = 12000) {
  const until = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < until) {
    last = await session.eval(expression);
    if (last?.present && last.inView) return last;
    await sleep(250);
  }
  return last;
}

async function main() {
  const { session, close } = await openBrowser({ port: PORT, profile: PROFILE, width: 1400, height: 950, scale: 1 });
  const send = session.send;
  const checks = {};
  const context = { key: KEY };
  let fixture = null;
  try {
    await session.navigate(baseUrl + "/login", 800);
    await session.login(baseUrl, adminEmail, adminPassword);
    fixture = await session.eval(`(async () => { ${API}
      const me = (await api("GET", "/auth/me")).body;
      const project = await api("POST", "/projects", { key: ${JSON.stringify(KEY)}, name: "Comment links" });
      const item = await api("POST", "/items", { project_id: project.body.id, title: "A long thread" });
      const ids = [];
      for (let i = 0; i < 130; i++) {
        ids.push((await api("POST", "/items/" + item.body.id + "/comments", { body: "Comment number " + i })).body.id);
      }
      const reply = await api("POST", "/comments/" + ids[8] + "/replies", { body: "A reply to comment 8" });
      const space = await api("POST", "/page-spaces", { name: "Links proof", slug: "links-proof-${STAMP}" });
      const page = await api("POST", "/pages", { space_id: space.body.id, title: "Discussed page",
        body: Array.from({ length: 40 }, (_, i) => "Paragraph " + i + " of a long page.").join("\\n\\n") });
      const pageComment = await api("POST", "/page/" + page.body.id + "/comments", { body: "The page comment we link to" });
      const colleague = await api("POST", "/users", { email: ${JSON.stringify(COLLEAGUE)}, name: "Colleague", password: ${JSON.stringify(PASSWORD)}, instance_role: "admin" });
      return { me, project: project.body, item: item.body, ids, reply: reply.body, space: space.body,
               page: page.body, pageComment: pageComment.body, colleague: colleague.body };
    })()`);
    context.replyStatus = !!fixture.reply?.id;

    // 1 — an old comment, beyond the first window.
    const old = fixture.ids[4];
    await session.navigate(`${baseUrl}/issues/${fixture.item.key}?comment=${old}`, 1500);
    const landed = await waitFor(session, landing(old));
    context.old = landed;
    checks["1. an old comment (126th newest) is in view and ringed"] = !!landed?.inView && landed.ringed;
    await session.screenshot(resolve(SHOTS, "old-comment.png"));

    // 2 — a reply: its thread opens.
    await session.navigate(`${baseUrl}/issues/${fixture.item.key}?comment=${fixture.reply.id}`, 1500);
    const reply = await waitFor(session, landing(fixture.reply.id));
    context.reply = reply;
    checks["2. a reply's thread opens and the reply is in view"] = !!reply?.inView;

    // 3 — Copy link.
    // Headless Chrome refuses clipboard writes from an unfocused document, so
    // the proof records what the button HANDS to the clipboard — the address
    // it builds is the claim; the browser's clipboard is not ours to test.
    await session.eval(`(() => {
      window.__copied = null;
      Object.defineProperty(Clipboard.prototype, "writeText", {
        configurable: true, value: async (text) => { window.__copied = text; },
      });
      window.prompt = (_message, value) => { window.__prompted = value; return null; };
    })()`);
    const target = fixture.ids[129];
    await session.eval(`document.querySelector('[data-comment-id="${target}"]').scrollIntoView({ block: "center" })`);
    context.copyClick = await clickAt(send, `[data-comment-id="${target}"] [data-copy-comment-link]`);
    await sleep(400);
    const copied = await session.eval(`window.__copied ?? window.__prompted ?? null`);
    context.copied = copied;
    checks["3. Copy link copies the issue's canonical comment address"] =
      copied === `${new URL(baseUrl).origin}/issues/${fixture.item.key}?comment=${target}`;

    // 4 — an id nobody can see: the issue just opens.
    await session.navigate(`${baseUrl}/issues/${fixture.item.key}?comment=00000000-0000-4000-8000-000000000000`, 3500);
    const plain = await session.eval(`(() => ({
      comments: document.querySelectorAll("[data-comment-id]").length,
      ringed: document.querySelectorAll("[data-comment-linked]").length,
      error: [...document.querySelectorAll("[role=alert]")].map((n) => n.textContent).join(" "),
    }))()`);
    context.unknown = plain;
    checks["4. an unknown/unreadable comment opens the issue as usual"] =
      plain.comments >= 50 && plain.ringed === 0 && !plain.error;

    // 5 — a page permalink carries the comment through its redirect.
    await session.navigate(`${baseUrl}/pages?pageId=${fixture.page.number}&comment=${fixture.pageComment.id}`, 1500);
    const onPage = await waitFor(session, landing(fixture.pageComment.id));
    const address = await session.eval(`location.pathname + location.search`);
    context.page = { ...onPage, address };
    checks["5. a page permalink lands on the discussion comment"] =
      !!onPage?.inView && address.startsWith(`/pages/links-proof-${STAMP}/`) && address.includes(`comment=${fixture.pageComment.id}`);
    await session.screenshot(resolve(SHOTS, "page-comment.png"));

    // 6 — a real notification: the colleague mentions you in a comment.
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    await session.login(baseUrl, COLLEAGUE, PASSWORD);
    const mention = await session.eval(`(async () => { ${API}
      return (await api("POST", "/items/${fixture.item.id}/comments",
        { body: "Look at this @[${fixture.me.name}](${fixture.me.id})" })).body;
    })()`);
    await session.eval(`fetch("/api/v1/auth/logout", { method: "POST" })`);
    await session.login(baseUrl, adminEmail, adminPassword);
    let row = null;
    for (let i = 0; i < 40 && !row; i++) {
      row = await session.eval(`(async () => { ${API}
        const list = (await api("GET", "/notifications?limit=50")).body;
        return (list.notifications ?? []).find((n) => n.detail?.comment_id === ${JSON.stringify(mention.id)}) ?? null;
      })()`);
      if (!row) await sleep(500);
    }
    context.notification = row ? { type: row.type, comment_id: row.detail.comment_id } : null;
    checks["6a. the mention notification carries the comment"] = !!row;
    if (row) {
      await session.navigate(`${baseUrl}/inbox`, 2500);
      // clickAt ships the matcher to the page as SOURCE, so it cannot close
      // over `fixture` — the key is written into the function instead.
      await clickAt(send, "button, a", new Function("text", `return text.includes(${JSON.stringify(fixture.item.key)})`));
      const opened = await waitFor(session, landing(mention.id));
      const where = await session.eval(`location.pathname + location.search`);
      context.inbox = { ...opened, where };
      checks["6b. opening it from the Inbox lands ON the comment"] =
        !!opened?.inView && where.includes(`comment=${mention.id}`);
      await session.screenshot(resolve(SHOTS, "from-inbox.png"));
    }
  } finally {
    if (fixture) {
      context.cleanup = await session.eval(`(async () => { ${API}
        return {
          page: (await api("DELETE", "/pages/${fixture.page.id}?hard=true")).status,
          space: (await api("DELETE", "/page-spaces/${fixture.space.id}")).status,
          project: (await api("DELETE", "/projects/${fixture.project.id}")).status,
          colleague: (await api("DELETE", "/users/${fixture.colleague.id}")).status,
        };
      })()`).catch((error) => String(error));
    }
    await close();
  }
  context.shots = SHOTS;
  process.exit(report(checks, context) ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
