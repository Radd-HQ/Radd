/**
 * Browser proof for RADD-1400 against the REAL backend: the command palette's Ask and the query
 * bar's natural-language ask are the ai plugin's contributed modes, and the host carries neither.
 *
 *   1. both modes are registered by the ai remote, loaded from /plugins/ai/;
 *   2. the palette's Ask answers as the palette's rows; the keyboard moves through them and Enter
 *      opens the issue in the same document;
 *   3. on a project's List view an empty bar opens on Ask; a question comes back as SLQ with an
 *      explanation, the bar applies it, and the list's rows are exactly `GET /items?q=` in that
 *      project;
 *   4. the timesheet's bar asks in the worklog dialect;
 *   5. no host chunk carries either mode — checked by CONTENT, both the chunks this page loaded
 *      and every chunk of the build on disk — while the ai remote's does;
 *   6. no console errors.
 *
 * Usage: node scripts/contributed-modes-proof.mjs <baseUrl> [email] [password]
 *
 * The modes' answers come from models the SERVER must reach (the chat role for natural language,
 * the embeddings role for Ask). Where it cannot, RADD_PROOF_STAND_IN_MODEL=1 answers the two in the
 * browser — natural language with a fixed real SLQ, Ask with the instance's own keyword hits — so
 * everything else (the remote, the host's rows and bar, the applied query, the list the server
 * runs) is still exercised for real; the report says which model answered. Nothing is written.
 */
import { readdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl = "http://127.0.0.1:8000", emailArg, passwordArg] = process.argv.slice(2);
const email = emailArg ?? process.env.RADD_PROOF_EMAIL ?? "admin@example.com";
const password = passwordArg ?? process.env.RADD_PROOF_PASSWORD ?? "change-me";
const standIn = process.env.RADD_PROOF_STAND_IN_MODEL === "1";
const PROJECT = process.env.RADD_PROOF_PROJECT ?? "GRQ";
const QUESTION = "issues about the render farm";
const STAND_IN_SLQ = 'title ~ "render farm"';
const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });
const context = { model: standIn ? "stand-in (answered in the browser)" : "live chat + embeddings roles" };
// What only the modes say: endpoints and copy. A host chunk carrying any of them carries a mode.
const MARKERS = ["/search/semantic", "/slq/nl", "search by meaning", "Search by meaning", "Semantic matches",
  "the answer lands as an SLQ query", "Ask AI for a query"];

async function waitFor(session, expression, attempts = 80, every = 250) {
  for (let i = 0; i < attempts; i += 1) {
    const value = await session.eval(expression);
    if (value) return value;
    await sleep(every);
  }
  return session.eval(expression);
}

const { session, close } = await openBrowser({ port: 9533, profile: resolve(process.env.TMPDIR || "/tmp", "radd-contributed-modes-proof") });
const press = async (key, code, keyCode, modifiers = 0) => {
  for (const type of ["rawKeyDown", "keyUp"]) await session.send("Input.dispatchKeyEvent", { type, key, code, windowsVirtualKeyCode: keyCode, modifiers });
};
const api = (path) => session.eval(`fetch("/api/v1${path}", {credentials: "include"}).then(async (r) => ({status: r.status, body: await r.json().catch(() => null)}))`);
const PALETTE = '[role=dialog][aria-label="Command palette"]';
try {
  // Record what the modes ask; with the stand-in, answer the two model-backed requests here.
  await session.send("Page.addScriptToEvaluateOnNewDocument", { source: `
    window.__asks = []; window.__semantic = [];
    const standIn = ${standIn};
    const original = window.fetch;
    const json = (data) => new Response(JSON.stringify(data), { headers: { "content-type": "application/json" } });
    window.fetch = async (input, init) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes("/api/v1/slq/nl") && init && init.body) {
        const body = JSON.parse(init.body);
        window.__asks.push(body);
        if (standIn) return json({ slq: body.dialect === "worklog" ? "author = me" : ${JSON.stringify(STAND_IN_SLQ)},
          explanation: "Stand-in: issues whose title mentions the render farm." });
      }
      if (url.includes("/api/v1/search/semantic")) {
        const q = new URL(url, location.origin).searchParams.get("q");
        window.__semantic.push(q);
        if (standIn) {
          const keyword = await original("/api/v1/search?limit=8&q=" + encodeURIComponent(q), { credentials: "include", signal: init && init.signal });
          const found = await keyword.json();
          return json({ enabled: true, docs: [], items: found.results.map((r, i) => ({ item_id: r.item_id, project_id: r.project_id,
            key: r.key, title: r.title, score: Math.round((0.9 - i * 0.05) * 1000) / 1000 })) });
        }
      }
      return original(input, init);
    };` });
  await session.navigate(`${baseUrl}/login`, 800);
  // The login endpoint throttles after a burst of sign-ins: wait for it rather than fail.
  let status = 0;
  for (let i = 0; i < 40 && status !== 204 && status !== 200; i += 1) {
    status = await session.login(baseUrl, email, password);
    if (status !== 204 && status !== 200) await sleep(3000);
  }
  check("signed in", status === 200 || status === 204, String(status));
  const aiStatus = await api("/ai/status");
  check("AI is configured with semantic search and natural-language queries on", aiStatus.body?.enabled
    && aiStatus.body.features?.semantic_search && aiStatus.body.features?.nl_slq, JSON.stringify(aiStatus.body));

  // 3. A project's List view: an empty bar opens on Ask.
  const project = (await api(`/projects/by-key/${PROJECT}`)).body;
  const views = (await api(`/views?project_id=${project.id}`)).body;
  const list = views.find((view) => view.view_type === "list");
  context.view = `${PROJECT} · ${list?.name}`;
  await session.navigate(`${baseUrl}/p/${PROJECT}/v/${list.id}`, 1500);
  check("the browser reports a hover-capable pointer", await session.hoverCapable());
  const askInput = 'input[aria-label="Ask AI for a query"]';
  check("an empty bar opens on Ask", await waitFor(session, `!!document.querySelector('${askInput}')`, 120));
  const loaded = await session.eval(`({
    remote: performance.getEntriesByType("resource").map((e) => e.name).filter((n) => n.includes("/plugins/ai/")),
    bar: globalThis.__RADD_SLOT_REGISTRY__.forSlot("query.input.mode").map((e) => e.plugin),
    toggle: [...document.querySelectorAll('[role=group][aria-label="Query mode"] button')].map((b) => b.textContent.trim()),
  })`);
  check("the ai remote was loaded from /plugins/ai/", loaded.remote.some((n) => n.includes("/plugins/ai/remoteEntry.js")), loaded.remote.join(","));
  check("the bar's natural-language ask is contributed by the ai remote alone", JSON.stringify(loaded.bar) === '["ai"]', JSON.stringify(loaded.bar));
  check("the toggle offers SLQ | Ask", JSON.stringify(loaded.toggle) === '["SLQ","Ask"]', JSON.stringify(loaded.toggle));

  await session.click(askInput);
  await session.send("Input.insertText", { text: QUESTION });
  await press("Enter", "Enter", 13);
  const slq = await waitFor(session, `(() => { const t = document.querySelector('textarea[aria-label="SLQ query"]'); return t && t.value ? t.value : ""; })()`, 120);
  const explanation = await waitFor(session, `document.querySelector("[data-query-explanation]")?.textContent ?? ""`, 40);
  const asked = await session.eval("window.__asks.at(-1)");
  context.slq = slq;
  context.explanation = explanation;
  check("the question went to the ai plugin in the items dialect", asked?.question === QUESTION && asked?.dialect === "items", JSON.stringify(asked));
  check("the answer lands in the SLQ editor, with its explanation", slq && explanation, `${slq} — ${explanation}`);
  // The list runs the applied query; its rows are the server's answer to the same SLQ in this project.
  const expected = (await api(`/items?project_id=${project.id}&limit=200&q=${encodeURIComponent(slq)}`)).body.map((item) => item.key).sort();
  context.expected = expected.length;
  const shown = await waitFor(session, `(() => {
    const keys = [...new Set([...document.querySelectorAll("[data-list-scroll] a[href^='/issues/']")].map((a) => decodeURIComponent(a.getAttribute("href").slice(8))))].sort();
    return keys.length === ${expected.length} ? keys : null;
  })()`, 120);
  check("the list runs the applied query: its rows are exactly GET /items?q=<slq> in the project",
    expected.length > 0 && JSON.stringify(shown) === JSON.stringify(expected),
    `${shown?.length ?? "(no match)"} shown vs ${expected.length} from the API`);
  await session.screenshot("/tmp/radd-contributed-modes-proof-list.png");

  // 4. The timesheet asks in the worklog dialect.
  await session.navigate(`${baseUrl}/timesheet`, 1500);
  await waitFor(session, `!!document.querySelector('${askInput}')`, 120);
  await session.click(askInput);
  await session.send("Input.insertText", { text: "my own worklogs" });
  await press("Enter", "Enter", 13);
  await waitFor(session, `document.querySelector('textarea[aria-label="SLQ query"]')?.value ?? ""`, 120);
  const worklogAsk = await session.eval("window.__asks.at(-1)");
  check("the timesheet's bar asks in the worklog dialect", worklogAsk?.dialect === "worklog", JSON.stringify(worklogAsk));

  // 2. The palette's Ask.
  await session.eval("window.__sameDocument = true");
  await press("k", "KeyK", 75, 2);
  await waitFor(session, `document.activeElement === document.querySelector('${PALETTE} input[aria-label="Search"]')`, 40);
  await session.send("Input.insertText", { text: "render farm" });
  const entry = await waitFor(session, `[...document.querySelectorAll('${PALETTE} button')].some((b) => b.innerText.includes("search by meaning"))`, 60);
  check("the palette offers Ask", entry);
  check("the palette's Ask is contributed by the ai remote alone",
    JSON.stringify(await session.eval(`globalThis.__RADD_SLOT_REGISTRY__.forSlot("palette.mode").map((e) => e.plugin)`)) === '["ai"]');
  await session.click(`${PALETTE} button`, (text) => text.includes("search by meaning"));
  const rows = await waitFor(session, `(() => {
    const buttons = [...document.querySelectorAll('${PALETTE} .max-h-\\\\[50vh\\\\] button')];
    return buttons.length >= 2 && document.querySelector('${PALETTE}').textContent.includes("Semantic matches")
      ? buttons.map((b) => b.innerText.replace(/\\s+/g, " ").trim()) : null;
  })()`, 120);
  check("Ask answers as the palette's own rows (key, title, score)", rows && rows.every((r) => /^[A-Z][A-Z0-9]*-\d+ .+ \d+%$/.test(r)), JSON.stringify(rows?.slice(0, 3)));
  check("the palette asked with what was typed", (await session.eval("window.__semantic.at(-1)")) === "render farm");
  await session.screenshot("/tmp/radd-contributed-modes-proof-palette.png");
  await press("ArrowDown", "ArrowDown", 40);
  const second = rows?.[1]?.split(" ")[0];
  const moved = await waitFor(session, `[...document.querySelectorAll('${PALETTE} .max-h-\\\\[50vh\\\\] button')][1]?.className.includes("bg-accent/15")`, 20);
  check("ArrowDown moves the active row", moved);
  await press("Enter", "Enter", 13);
  const landed = await waitFor(session, `location.pathname === "/issues/${second}" && !document.querySelector('${PALETTE}')
    && document.body.innerText.includes(${JSON.stringify(second ?? "")})`, 80);
  check("Enter opens the second row's issue in the same document", landed && (await session.eval("window.__sameDocument")) === true, second);

  // 5. The host carries neither mode — by CONTENT.
  const chunks = await session.eval(`performance.getEntriesByType("resource").map((e) => e.name).filter((n) => /\\.js(\\?|$)/.test(n))`);
  const host = chunks.filter((n) => !n.includes("/plugins/"));
  const ai = chunks.filter((n) => n.includes("/plugins/ai/"));
  const scan = (urls) => session.eval(`Promise.all(${JSON.stringify(urls)}.map((u) => fetch(u).then((r) => r.text())
    .then((t) => [u, ${JSON.stringify(MARKERS)}.filter((m) => t.includes(m))])))`);
  const hostHits = (await scan(host)).filter(([, found]) => found.length);
  const aiHits = (await scan(ai)).flatMap(([, found]) => found);
  context.hostChunksLoaded = host.length;
  check("no host chunk this page loaded carries a mode", host.length > 20 && hostHits.length === 0, JSON.stringify(hostHits).slice(0, 300));
  check("the ai remote's chunk carries both", ["/search/semantic", "/slq/nl", "Search by meaning", "the answer lands as an SLQ query"].every((m) => aiHits.includes(m)), aiHits.join(","));
  const dist = fileURLToPath(new URL("../dist/assets/", import.meta.url));
  const built = readdirSync(dist).filter((f) => f.endsWith(".js"));
  const builtHits = built.filter((f) => MARKERS.some((m) => readFileSync(resolve(dist, f), "utf8").includes(m)));
  const served = await session.eval(`fetch("/").then((r) => r.text()).then((t) => (t.match(/assets\\/(index-[^"]+\\.js)/) ?? [])[1] ?? "")`);
  context.hostChunksBuilt = built.length;
  check("…nor does any chunk of the build this server serves", served && built.includes(served) && builtHits.length === 0,
    `${served} served; ${builtHits.join(",")}`);

  check("no console errors", session.consoleErrors.length === 0, session.consoleErrors.slice(0, 3).join(" | "));
} catch (error) {
  check("the proof ran to its end", false, String(error?.message ?? error).split("\n")[0]);
} finally {
  await close();
}
const failed = report(Object.fromEntries(checks.map((c) => [c.ok ? c.name : `${c.name} — ${c.detail}`, c.ok])), { proof: "contributed modes (RADD-1400)", ...context });
process.exit(failed ? 1 : 0);
