/** RADD-1225: real browser/HTTP, synthetic page; never writes to an instance. */
import assert from "node:assert/strict";
import http from "node:http";
import {readFileSync, existsSync, statSync} from "node:fs";
import {mkdtemp} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {openBrowser} from "./lib/cdp.mjs";

const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const user = {id: "admin", name: "Fixture Admin", email: "fixture@example.test", global_role: "admin", permissions: ["*"], timezone: "UTC"};
const space = {id: "space", slug: "handbook", name: "Handbook", permissions: ["*"], position: 0, page_count: 1};
const early = "Review this opening passage";
const late = "Review this final passage";
const codeQuote = "deep_code_annotation_target";
const page = {id: "page", number: 1, space_id: space.id, space, slug: "long-page", path: "long-page", title: "Long page annotations", parent_id: null,
  position: 0, version: 1, created_by: user.id, updated_by: user.id, created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null, labels: [], breadcrumb: [],
  body: `## Introduction\n\n${early}.\n\n` + Array.from({length: 45}, (_, i) => `## Section ${i + 1}\n\nA deliberately long document. Paragraph ${i + 1} keeps its own position while the comments stay available.\n\n`).join("") + `## Conclusion\n\n${late}.\n\nRepeated ambiguous phrase.\n\nRepeated ambiguous phrase.`};
page.body += "\n\n```text\n" + Array.from({length: 100}, (_, i) => `configuration_line_${i}`).join("\n") + `\n${codeQuote}\n` + "```";
let comments = [early, late, "Removed passage", "Repeated ambiguous phrase", codeQuote].map((quote, i) => ({id: `comment-${i}`, entity_type: "page", entity_id: page.id, author: user,
  body: `Please review annotation ${i + 1}.`, visibility: "public", visible_to_teams: [], created_at: "2026-01-01", updated_at: "2026-01-01", anchor: {quote}, resolved_at: null, resolved_by: null}));
const requests = [];
const replies = [{id: "reply-0", parent_comment_id: "comment-0", entity_type: "page", entity_id: page.id,
  author: {id: "colleague", name: "Fixture Colleague"}, body: "The original reply", created_at: "2026-01-02", updated_at: "2026-01-02", anchor: null, resolved_at: null}];
comments[0].reply_count = 1;
let failReply = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname.startsWith("/api/")) {
    const route = url.pathname.replace("/api/v1", "");
    requests.push({route, method: req.method});
    let data = [], status = 200;
    if (route === "/auth/me") data = user;
    else if (route.includes("capabilities")) data = {capabilities: [], nav: [], plugins: ["pages"], ui: []};
    else if (route === "/preferences") data = {};
    else if (route === "/projects/summary") data = {total: 0, related_count: 0, permissions: ["*"]};
    else if (route === "/page-spaces/summary") data = {total: 1, permissions: ["*"]};
    else if (route === "/page-spaces") data = [space];
    else if (route === "/page-spaces/by-identity/handbook" || route === "/page-spaces/space") data = space;
    else if (route === "/page-spaces/space/pages") data = [page];
    else if (route === "/pages/by-path/handbook/long-page" || route === "/pages/page") data = page;
    else if (route.endsWith("/comments/feed")) data = {comments: url.searchParams.get("section") === "inline" ? comments : [], older_cursor: null};
    else if (route.endsWith("/replies")) {
      const rootId = route.split("/")[2];
      if (req.method === "POST") {
        let body = ""; for await (const chunk of req) body += chunk;
        if (failReply) {status = 503; data = {detail: "Try replying again"};}
        else {
          data = {...replies[0], id: `reply-${replies.length}`, parent_comment_id: rootId, author: user, body: JSON.parse(body).body};
          replies.push(data);
          comments = comments.map(row => row.id === rootId ? {...row, reply_count: replies.filter(reply => reply.parent_comment_id === rootId).length} : row);
        }
      } else data = {comments: replies.filter(reply => reply.parent_comment_id === rootId), older_cursor: null};
    }
    else if (route.startsWith("/comments/") && req.method === "POST") {
      const [, , id, action] = route.split("/");
      comments = comments.map(row => row.id === id ? {...row, resolved_at: action === "resolve" ? "2026-01-02" : null} : row);
      data = comments.find(row => row.id === id);
    }
    else if (route.includes("/collab/")) {status = 404; data = {detail: "Collaboration unavailable in this fixture"};}
    else if (route.endsWith("/watch")) data = {watching: false};
    else if (route.includes("/notifications")) data = {items: [], notifications: [], unread_count: 0, total: 0};
    else if (route === "/ai/status") data = {enabled: false, features: {}};
    else if (route === "/instance") data = {work_week_days: ["mon"], timelog_hours_per_day: 8, timelog_days_per_week: 5};
    else if (route.includes("/resolve")) data = {value: false};
    else if (route === "/users/directory") data = [user];
    res.writeHead(status, {"content-type": "application/json"}); res.end(JSON.stringify(data)); return;
  }
  const candidate = path.join(dist, url.pathname);
  const file = existsSync(candidate) && statSync(candidate).isFile() ? candidate : path.join(dist, "index.html");
  res.writeHead(200, {"content-type": file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "text/html"});
  res.end(readFileSync(file));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
let browser;
try {
  browser = await openBrowser({port: 18846, profile: await mkdtemp("/tmp/radd-page-comments-"), width: 1600, height: 1000, scale: 1});
  const s = browser.session;
  const until = async (expression) => {
    for (let i = 0; i < 150; i++) {if (await s.eval(expression)) return; await new Promise(r => setTimeout(r, 50));}
    throw Error(`Condition did not settle: ${expression}`);
  };
  const quote = text => `[aria-label=${JSON.stringify(`Go to passage: ${text}`)}]`;
  const visit = () => s.navigate(`http://127.0.0.1:${server.address().port}/pages/handbook/long-page`);
  const focusedRect = `(() => {const r = [...CSS.highlights.get('radd-inline-comment-focus')][0]?.getBoundingClientRect(); return r && {top:r.top,bottom:r.bottom};})()`;
  await visit();
  await until(`!!document.querySelector(${JSON.stringify(quote(late))}) && !document.querySelector(${JSON.stringify(quote(late))}).disabled`);
  assert(await s.eval(`document.querySelector('[data-page-comment-sidebar]').getBoundingClientRect().left > document.querySelector('[data-page-body]').getBoundingClientRect().right`), "sidebar must be to the right");
  for (const text of ["Removed passage", "Repeated ambiguous phrase"]) assert(await s.eval(`document.querySelector(${JSON.stringify(quote(text))}).disabled`), "unsafe anchor must not jump");
  await s.click(quote(late));
  await until(`(${focusedRect})?.top > 100 && (${focusedRect})?.bottom < innerHeight - 100`);
  assert(await s.eval(`document.querySelector('[data-page-comment-sidebar]').getBoundingClientRect().top >= 0`));
  await s.screenshot("/tmp/radd-page-comments-desktop.png");
  await s.click(quote(codeQuote));
  await until(`(${focusedRect})?.top > 100 && (${focusedRect})?.bottom < innerHeight - 100`);
  // A selection inside CodeMirror must create a quote from the source once,
  // without its hidden duplicate, line numbers, or toolbar labels.
  await s.eval(`(() => {const r = [...CSS.highlights.get('radd-inline-comment-focus')][0].cloneRange(); getSelection().removeAllRanges(); getSelection().addRange(r); document.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));})()`);
  await until(`!!document.querySelector('button.fixed')`);
  await s.click('button.fixed', text => text.trim() === "Comment");
  await until(`document.querySelector('[data-inline-comment-rail] .border-accent > p')?.textContent === ${JSON.stringify(`“${codeQuote}”`)}`);
  await s.click('[data-inline-comment-rail] button', text => text.trim() === "Cancel");
  await s.eval(`getSelection().removeAllRanges()`);
  // Keyboard navigation is available, not just pointer hover.
  await s.eval(`document.querySelector(${JSON.stringify(quote(early))}).focus()`);
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", text: "\r", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13});
  await s.send("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13});
  await until(`CSS.highlights.get('radd-inline-comment-focus') && [...CSS.highlights.get('radd-inline-comment-focus')][0]?.toString() === ${JSON.stringify(early)}`);
  await until(`(${focusedRect})?.top > 100 && (${focusedRect})?.bottom < innerHeight - 100`);
  // Clicking the highlighted text returns focus to its thread.
  const point = await s.eval(`(() => {const r = [...CSS.highlights.get('radd-inline-comment-focus')][0].getClientRects()[0]; return {x:r.left+5,y:r.top+r.height/2};})()`);
  await s.eval(`document.querySelector(${JSON.stringify(quote(late))}).focus({preventScroll:true})`);
  await until(`CSS.highlights.get('radd-inline-comment-focus') && [...CSS.highlights.get('radd-inline-comment-focus')][0]?.toString() === ${JSON.stringify(late)}`);
  const replyRequests = () => requests.filter(request => request.route.endsWith('/replies'));
  assert.equal(replyRequests().length, 0, "page rendering must not eagerly fetch threads");
  await s.send("Input.dispatchMouseEvent", {type: "mouseMoved", ...point});
  await until(`!!document.querySelector('[aria-label="Inline comment preview"]')`);
  assert.equal(replyRequests().length, 0, "hover must reuse loaded annotation data");
  const preview = await s.eval(`(() => {const r = document.querySelector('[data-page-comment-popover]').getBoundingClientRect(); return {x:r.left+20,y:r.top+20,left:r.left,top:r.top};})()`);
  assert(Math.abs(preview.left - point.x) < 350 && Math.abs(preview.top - point.y) < 450, "preview should be near the pointer");
  await s.send("Input.dispatchMouseEvent", {type: "mouseMoved", x: preview.x, y: preview.y});
  assert(await s.eval(`!!document.querySelector('[aria-label="Inline comment preview"]')`));
  await s.send("Input.dispatchMouseEvent", {type: "mouseMoved", x: 10, y: 100});
  await until(`!document.querySelector('[data-page-comment-popover]')`);
  await s.send("Input.dispatchMouseEvent", {type: "mousePressed", button: "left", clickCount: 1, ...point});
  await s.send("Input.dispatchMouseEvent", {type: "mouseReleased", button: "left", clickCount: 1, ...point});
  await until(`document.querySelector('[data-comment-id="comment-0"]').classList.contains('border-strong')`);
  await until(`document.querySelector('[aria-label="Inline comment thread"]')?.textContent.includes('The original reply')`);
  await s.click('[data-page-comment-popover] textarea');
  await s.send("Input.insertText", {text: "My persistent reply"});
  await s.send("Input.dispatchKeyEvent", {type: "keyDown", key: "Escape", code: "Escape"});
  await until(`!document.querySelector('[data-page-comment-popover]')`);
  await s.send("Input.dispatchMouseEvent", {type: "mousePressed", button: "left", clickCount: 1, ...point});
  await s.send("Input.dispatchMouseEvent", {type: "mouseReleased", button: "left", clickCount: 1, ...point});
  await until(`document.querySelector('[data-page-comment-popover] textarea')?.value === 'My persistent reply'`);
  failReply = true;
  await s.click('[data-page-comment-popover] button[type="submit"]');
  await until(`document.querySelector('[data-page-comment-popover] [role="alert"]')?.textContent.includes('Try replying again')`);
  assert.equal(await s.eval(`document.querySelector('[data-page-comment-popover] textarea').value`), "My persistent reply");
  failReply = false;
  await s.click('[data-page-comment-popover] button[type="submit"]');
  await until(`document.querySelector('[data-page-comment-popover] textarea')?.value === '' && document.querySelector('[data-page-comment-popover]').textContent.includes('My persistent reply')`);
  assert.equal(replies.filter(reply => reply.body === "My persistent reply").length, 1);
  await s.screenshot('/tmp/radd-page-comment-thread.png');
  await s.click('[aria-label="Close inline comment"]');
  await s.click('[data-comment-id="comment-0"] button', text => text === "Resolve");
  await until(`document.body.innerText.includes('Resolved (1)')`);
  await s.click("button", text => text === "Resolved (1)");
  await s.click('[data-comment-id="comment-0"] button', text => text === "Reopen");
  await until(`!document.body.innerText.includes('Resolved (1)')`);
  await s.click('[aria-label="Edit page"]');
  await until(`!!document.querySelector('[contenteditable="true"].ProseMirror') && document.querySelector('[contenteditable="true"].ProseMirror').textContent.includes(${JSON.stringify(late)})`);
  await s.click(quote(late));
  await until(`(${focusedRect})?.top > 100 && (${focusedRect})?.bottom < innerHeight - 100`);
  // Genuine editor input mutates the document; highlights must follow it.
  await s.eval(`(() => {const e = document.querySelector('[contenteditable="true"].ProseMirror'); e.focus(); const r = document.createRange(); r.selectNodeContents(e); r.collapse(true); getSelection().removeAllRanges(); getSelection().addRange(r);})()`);
  await s.send("Input.insertText", {text: "New opening words. "});
  await until(`CSS.highlights.get('radd-inline-comment-focus') && [...CSS.highlights.get('radd-inline-comment-focus')][0]?.toString() === ${JSON.stringify(late)}`);
  await s.click(quote(codeQuote));
  await until(`(${focusedRect})?.top > 100 && (${focusedRect})?.bottom < innerHeight - 100`);
  await s.send("Emulation.setDeviceMetricsOverride", {width: 390, height: 844, deviceScaleFactor: 1, mobile: false});
  await visit();
  await until(`!!document.querySelector(${JSON.stringify(quote(late))}) && !document.querySelector(${JSON.stringify(quote(late))}).disabled`);
  await s.click(quote(late));
  await until(`(${focusedRect})?.top > document.querySelector('[data-page-comment-sidebar]').getBoundingClientRect().bottom && (${focusedRect})?.bottom < innerHeight`);
  assert(await s.eval(`document.documentElement.scrollWidth <= innerWidth`), "mobile horizontal overflow");
  await s.screenshot("/tmp/radd-page-comments-mobile.png");
  const mobilePoint = await s.eval(`(() => {const r = [...CSS.highlights.get('radd-inline-comment-focus')][0].getClientRects()[0]; return {x:r.left+5,y:r.top+r.height/2};})()`);
  await s.send("Input.dispatchMouseEvent", {type: "mousePressed", button: "left", clickCount: 1, ...mobilePoint});
  await s.send("Input.dispatchMouseEvent", {type: "mouseReleased", button: "left", clickCount: 1, ...mobilePoint});
  await until(`!!document.querySelector('[aria-label="Inline comment thread"] textarea')`);
  assert(await s.eval(`(() => {const r=document.querySelector('[data-page-comment-popover]').getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight;})()`));
  await s.screenshot('/tmp/radd-page-comment-thread-mobile.png');
  assert.equal(s.consoleErrors.filter(e => e.startsWith("EXCEPTION:")).length, 0, s.consoleErrors.join("\n"));
  console.log("Page annotations: sidebar, prose/code jumps, hover previews, pinned threads, lazy replies, preserved drafts, failed reply retry, keyboard dismissal, orphan safety, resolve/reopen, editor input and mobile bounds passed.");
} catch (error) {
  await browser?.session.screenshot("/tmp/radd-page-comments-failure.png");
  console.error(await browser?.session.eval(`JSON.stringify({sidebar:document.querySelector('[data-page-comment-sidebar]')?.getBoundingClientRect(),focus:[...(CSS.highlights.get('radd-inline-comment-focus')??[])].map(r=>r.getBoundingClientRect())})`));
  console.error(JSON.stringify({requests, errors: browser?.session.consoleErrors, body: await browser?.session.eval("document.body.innerText")}, null, 2));
  throw error;
} finally {
  await browser?.close(); server.closeAllConnections(); server.close();
}
