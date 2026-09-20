/**
 * RADD-1274: an editor AI run cannot lose a media block, an image or an
 * extension, and the review names the inline comments it strands.
 *
 * A page holds a paragraph with two anchored comments, a `radd:media` fence and
 * an image. A stand-in model returns a summary that keeps the media placeholder,
 * omits the image placeholder, and drops both commented passages. Expected:
 *   - the model was sent placeholders and not one line of fence/image syntax;
 *   - the review says 1 protected block was kept at the end and 2 comments
 *     would be detached, with "resolve them" on by default;
 *   - after Accept all the editor still holds the media block AND the image,
 *     the saved page body still holds both, and both comments are resolved.
 *
 *   node scripts/ai-protect-proof.mjs [baseUrl] [email] [password]
 *   (defaults: http://127.0.0.1:8000, RADD_PROOF_EMAIL / RADD_PROOF_PASSWORD,
 *    else admin@example.com / change-me)
 */
import { createServer } from "node:http";
import { mkdir } from "node:fs/promises";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const baseUrl = process.argv[2] || process.env.RADD_PROOF_BASE_URL || "http://127.0.0.1:8000";
const email = process.argv[3] || process.env.RADD_PROOF_EMAIL || "admin@example.com";
const password = process.argv[4] || process.env.RADD_PROOF_PASSWORD || "change-me";
const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-ai-protect-proof";
const MOCK_PORT = 8117;
const MOCK_NAME = "protect-proof-mock";

const P1 = "The cache is invalidated on write and never on read, which keeps reads cheap.";
const P2 = "Deploys happen on Tuesday after the standup, never on a Friday.";
const MEDIA = '```radd:media\n{"src": "/api/v1/attachments/00000000-0000-0000-0000-000000000001", "kind": "video", "title": "Standup.mp4"}\n```';
const IMAGE = "![whiteboard](/api/v1/attachments/00000000-0000-0000-0000-000000000002)";
const SEED = `# Standup notes\n\n${P1}\n\n${MEDIA}\n\n${P2}\n\n${IMAGE}\n`;
// Keeps ⟦keep-1⟧ (the media), drops ⟦keep-2⟧ (the image) and both passages.
const REPLY = "# Summary\n\n- The standup covered caching and the deploy cadence.\n\n⟦keep-1⟧\n\n- Two decisions were recorded.\n";

/** The stand-in model: OpenAI stream shape, and it REMEMBERS what it was sent. */
function startMock(port) {
  const seen = [];
  const server = createServer((req, res) => {
    if (req.url?.startsWith("/v1/models")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ data: [{ id: "mock-1", object: "model" }] }));
      return;
    }
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      seen.push(body);
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      const words = REPLY.split(" ");
      let i = 0;
      const tick = setInterval(() => {
        if (i >= words.length) {
          clearInterval(tick);
          res.write("data: [DONE]\n\n");
          res.end();
          return;
        }
        const delta = (i === 0 ? "" : " ") + words[i++];
        res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: delta } }] })}\n\n`);
      }, 20);
    });
  });
  return new Promise((resolve) =>
    server.listen(port, "127.0.0.1", () => resolve({ seen, close: () => server.close() })),
  );
}

async function waitFor(session, expression, tries = 60) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(500);
  }
  return false;
}

async function main() {
  await mkdir(output, { recursive: true });
  const mock = await startMock(MOCK_PORT);
  const { session, close } = await openBrowser({ port: 9533, profile: output + "/chrome", width: 1440, height: 1100 });
  const checks = {};
  const api = (expression) => session.eval(`(async () => { ${expression} })()`);
  let page = null;
  let providerId = null;
  let previousRole = null;
  try {
    await session.navigate(baseUrl + "/login", 1200);
    checks.loggedIn = (await session.login(baseUrl, email, password)) === 204;
    checks.hoverCapable = await session.hoverCapable();

    // --- the stand-in model takes the chat role for the duration
    previousRole = await api(`
      const roles = await (await fetch("/api/v1/ai/roles", {credentials:"include"})).json();
      const chat = roles.find((r) => r.role === "chat") ?? null;
      return chat && chat.provider_name !== ${JSON.stringify(MOCK_NAME)} ? chat : null;`);
    providerId = await api(`
      const providers = await (await fetch("/api/v1/ai/providers", {credentials:"include"})).json();
      for (const p of providers.filter((p) => p.name === ${JSON.stringify(MOCK_NAME)}))
        await fetch("/api/v1/ai/providers/" + p.id, { method: "DELETE", credentials: "include" });
      const provider = await (await fetch("/api/v1/ai/providers", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ name: ${JSON.stringify(MOCK_NAME)}, wire_shape: "openai",
                               base_url: "http://127.0.0.1:${MOCK_PORT}/v1", default_model: "mock-1" }),
      })).json();
      await fetch("/api/v1/ai/roles/chat", {
        method: "PUT", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ provider_id: provider.id, model: "mock-1" }),
      });
      return provider.id;`);

    // --- a page with the two blocks and two anchored comments
    page = await api(`
      const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
      const space = spaces[0];
      const page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "AI protect proof " + Date.now().toString(36), body: ${JSON.stringify(SEED)} }),
      })).json();
      const comment = async (quote, prefix, suffix) => (await (await fetch("/api/v1/page/" + page.id + "/comments", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: "Is this still true?", anchor: { quote, prefix, suffix } }),
      })).json()).id;
      const c1 = await comment("invalidated on write", "The cache is ", " and never on read");
      const c2 = await comment("happen on Tuesday", "Deploys ", " after the standup");
      return { id: page.id, slug: page.slug, space: space.slug, path: page.path, comments: [c1, c2] };`);
    checks.seeded = Boolean(page?.id && page.comments.every(Boolean));

    await session.navigate(`${baseUrl}/pages/${page.space}/${page.slug}`, 2500);
    await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
    checks.editorOpened = await waitFor(session, `!!document.querySelector(".ProseMirror")`, 30);
    await sleep(1500);
    checks.blocksInEditorBefore = await session.eval(
      `!!document.querySelector('.ProseMirror [data-extension="media"]') && !!document.querySelector(".ProseMirror img")`,
    );

    // --- the run: toolbar AI → Summarize (whole document)
    await session.click('[role="toolbar"] button[aria-label="AI"]');
    await sleep(400);
    await session.click("[data-ai-toolbar-menu] button", (t) => /summar/i.test(t));
    checks.reviewOpened = await waitFor(session, `document.querySelectorAll(".milkdown-diff-controls").length > 0`, 60);
    await sleep(500);
    await session.screenshot(output + "/review.png");

    const sent = mock.seen[mock.seen.length - 1] ?? "";
    checks.modelSawPlaceholders = sent.includes("\\u27e6keep-1\\u27e7") || sent.includes("⟦keep-1⟧");
    checks.modelSawNoSyntax = !/radd:media|!\[whiteboard|attachments\//.test(sent);
    checks.promptCarriesTheRule = /keep-N/.test(sent);
    const panel = await session.eval(`({
      dropped: document.querySelector("[data-ai-dropped-blocks]")?.textContent ?? null,
      detached: document.querySelector("[data-ai-detached-comments]")?.textContent ?? null,
      resolveChecked: document.querySelector("[data-ai-detached-comments] input")?.checked ?? null,
    })`);
    checks.panelReportsDroppedBlock = /left out 1 protected block/.test(panel.dropped ?? "");
    checks.panelCountsTwoComments = /passages of 2 open comments/.test(panel.detached ?? "");
    checks.resolveOnByDefault = panel.resolveChecked === true;

    // --- accept everything
    await session.click("[data-ai-run-panel] button", (t) => /accept all/i.test(t));
    checks.reviewClosed = await waitFor(session, `document.querySelectorAll(".milkdown-diff-controls").length === 0`, 30);
    await sleep(3500); // the room's elected saver writes 1.5 s after the change
    await session.screenshot(output + "/accepted.png");
    checks.mediaSurvived = await session.eval(`!!document.querySelector('.ProseMirror [data-extension="media"]')`);
    checks.imageSurvived = await session.eval(`!!document.querySelector(".ProseMirror img")`);
    checks.summaryLanded = await session.eval(`/Two decisions were recorded/.test(document.querySelector(".ProseMirror").textContent)`);
    const saved = await api(`
      const p = await (await fetch("/api/v1/pages/${page.id}", {credentials:"include"})).json();
      return p.body;`);
    checks.savedBodyKeepsMedia = typeof saved === "string" && saved.includes("radd:media") && saved.includes("Standup.mp4");
    checks.savedBodyKeepsImage = typeof saved === "string" && saved.includes("![whiteboard]");
    checks.savedBodyIsTheSummary = typeof saved === "string" && saved.includes("Two decisions were recorded");
    const resolved = await api(`
      const feed = await (await fetch("/api/v1/page/${page.id}/comments/feed?section=inline&limit=50", {credentials:"include"})).json();
      const rows = feed.comments ?? feed.items ?? feed.rows ?? [];
      return ${JSON.stringify(page.comments)}.map((id) => Boolean(rows.find((r) => r.id === id)?.resolved_at));`);
    checks.bothCommentsResolved = Array.isArray(resolved) && resolved.length === 2 && resolved.every(Boolean);
    checks.noConsoleErrors = session.consoleErrors.length === 0;
    if (!checks.noConsoleErrors) console.error(session.consoleErrors);
    return report(checks, { panel, savedHead: String(saved).slice(0, 200) });
  } finally {
    try {
      await api(`
        ${page ? `await fetch("/api/v1/pages/${page.id}", { method: "DELETE", credentials: "include" });` : ""}
        ${previousRole
          ? `await fetch("/api/v1/ai/roles/chat", { method: "PUT", credentials: "include", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ provider_id: ${JSON.stringify(previousRole.provider_id)}, model: ${JSON.stringify(previousRole.model)} }) });`
          : `await fetch("/api/v1/ai/roles/chat", { method: "DELETE", credentials: "include" });`}
        ${providerId ? `await fetch("/api/v1/ai/providers/${providerId}", { method: "DELETE", credentials: "include" });` : ""}
        return true;`);
    } catch (error) {
      console.error("teardown failed:", error);
    }
    await close();
    mock.close();
  }
}

process.exitCode = await main();
