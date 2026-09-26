/**
 * Browser proof for RADD-1401 against the REAL backend: the public survey page is the csat plugin's
 * `public.page` contribution, and how a mailed body reads is the mailintake plugin's `content.body`
 * claim — the host names neither.
 *
 *   1. over REST, a throwaway project with one issue, moved into a done state, and a comment whose
 *      body ends in a signature;
 *   2. what the workers and intake would write — the issue's survey and the signature annotations on
 *      the comment and the description — through the app's own services (this proof runs its
 *      backend without workers, and mail intake needs a mailbox);
 *   3. a FRESH, anonymous browser profile opens the survey link: /auth/me answers the Anyone
 *      principal, the page is drawn by /plugins/csat/ inside the host's public frame (no shell),
 *      `?rating=5` preselects, a rating and comment submit, the visitor stays on the page, and the
 *      issue's GET /items/{id}/csat returns exactly what was sent;
 *   4. signed in, the issue page draws the description and the comment with their signatures folded
 *      under "Show signature" (the claim comes from /plugins/mailintake/); unfolding shows the
 *      signature, "Not a signature" drops the comment's annotation (GET confirms) and the comment
 *      reads whole;
 *   5. no console errors in either browser; the project is deleted again (the fixture cascades).
 *
 * Usage (from web/): node scripts/csat-mail-plugins-proof.mjs <baseUrl> [email] [password]
 * The backend must come from this checkout; the fixture helper runs in ../server against the
 * database its settings name, which must be the one that backend serves.
 */
import { execFileSync } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { openBrowser, PAGE_API, report, sleep, waitFor } from "./lib/cdp.mjs";
import { proofArgs } from "./lib/proof.mjs";

const { baseUrl, email, password } = proofArgs();
const TMP = process.env.TMPDIR || "/tmp";
const SERVER = resolve(dirname(fileURLToPath(import.meta.url)), "../../server");
const key = `CM${Date.now().toString(36).slice(-4).toUpperCase()}`;
const COMMENT_SIGNATURE = "Cheers,\nPat Requester\nFloor 3 reception";
const DESCRIPTION_SIGNATURE = "Kind regards,\nPat Requester";

const checks = [];
const check = (name, ok, detail = "") => checks.push({ name, ok: Boolean(ok), detail });
const SLOW = { attempts: 80 };

// Stands in for csat's sender (a worker) and mail intake's signature detection: the same rows.
const STAMP = `
import asyncio, json, sys, uuid
from radd.config import settings
from radd.kernel import load_plugins
load_plugins(settings.modules)
from radd.db import SessionLocal
from radd.modules.comments import service as comments
from radd.modules.csat import service as csat
from radd.modules.items import service as items

async def main(item_id, comment_id, comment_signature, description_signature):
    async with SessionLocal() as session:
        survey = await csat.create_survey(session, item_id=uuid.UUID(item_id))
        await comments.annotate_email_signature(session, uuid.UUID(comment_id), comment_signature)
        await items.annotate_email_signature(session, uuid.UUID(item_id), description_signature)
        await session.commit()
        print("TOKEN=" + json.dumps(survey.token))

asyncio.run(main(*sys.argv[1:]))
`;

/** Sign in, retrying while the login throttle holds (it answers 429 after ~20 in a row). */
async function signIn(session) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const status = await session.login(baseUrl, email, password);
    if (status === 200 || status === 204) return status;
    if (status !== 429) return status;
    await sleep(3000);
  }
  return 429;
}

const agent = await openBrowser({ port: 9541, profile: await mkdtemp(resolve(TMP, "radd-csat-mail-agent-")) });
let visitor = null;
let world = null;
try {
  const a = agent.session;
  await a.navigate(`${baseUrl}/login`, 800);
  const status = await signIn(a);
  check("signed in", status === 200 || status === 204, `login → ${status}`);

  // 1. The world, over REST.
  world = await a.eval(`(async () => { ${PAGE_API}
    const project = await api("POST", "/projects", { key: ${JSON.stringify(key)}, name: "CSAT and mail proof" });
    const id = project.body.id;
    const item = await api("POST", "/items", { project_id: id, title: "Proof: the printer on floor 3 jams",
      description: "The printer jams on every job since Monday.\\n\\n" + ${JSON.stringify(DESCRIPTION_SIGNATURE)} });
    const states = await api("GET", "/states?project_id=" + id);
    const done = (states.body ?? []).find((s) => (s.category_key ?? s.category) === "done");
    const moved = await api("PATCH", "/items/" + item.body.id, { state_id: done?.id });
    const comment = await api("POST", "/items/" + item.body.id + "/comments",
      { body: "Still jamming after the fix.\\n\\n" + ${JSON.stringify(COMMENT_SIGNATURE)} });
    return { projectId: id, itemId: item.body?.id, itemKey: item.body?.key, commentId: comment.body?.id,
      doneState: done?.name, stateAfter: moved.body?.state?.name,
      status: [project.status, item.status, states.status, moved.status, comment.status] };
  })()`);
  check("a throwaway project, an issue moved into a done state and a comment exist",
    world.status.join() === "201,201,200,200,201" && world.stateAfter === world.doneState,
    JSON.stringify(world));

  // 2. The rows the workers and intake would have written.
  const out = execFileSync("uv", ["run", "python", "-c", STAMP, world.itemId, world.commentId,
    COMMENT_SIGNATURE, DESCRIPTION_SIGNATURE], { cwd: SERVER, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] });
  const token = JSON.parse(/^TOKEN=(.*)$/m.exec(out)?.[1] ?? "null");
  check("a survey token was issued for the resolved issue", typeof token === "string" && token.length > 20, String(token));

  // 3. The anonymous visitor, in a profile that has never signed in.
  visitor = await openBrowser({ port: 9542, profile: await mkdtemp(resolve(TMP, "radd-csat-mail-visitor-")) });
  const v = visitor.session;
  const link = `${baseUrl}/public/csat/${encodeURIComponent(token)}`;
  await v.navigate(`${link}?rating=5`, 1500);
  const me = await v.eval(`fetch("/api/v1/auth/me").then((r) => r.json())`);
  check("the visitor is the anonymous Anyone principal", me.anonymous === true, JSON.stringify({ anonymous: me.anonymous, name: me.name }));
  const drawn = await waitFor(v, `!!document.querySelector('[data-csat-survey]:not([data-csat-survey="unavailable"])')`, SLOW);
  check("the survey page renders for the visitor", drawn, await v.eval(`document.body.innerText.slice(0, 200)`));
  const remotes = await v.eval(`performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname).filter((p) => p.startsWith("/plugins/"))`);
  check("the page is drawn by the csat remote (/plugins/csat/remoteEntry.js)", remotes.includes("/plugins/csat/remoteEntry.js"), JSON.stringify(remotes));
  const frame = await v.eval(`({ brand: document.querySelector("h1")?.textContent, shell: !!document.querySelector("aside"),
    title: document.body.innerText.includes(${JSON.stringify(world.itemKey)}) })`);
  check("inside the host's public frame, with no app shell, naming the issue", frame.brand === "Radd" && !frame.shell && frame.title, JSON.stringify(frame));
  check("?rating=5 preselects five stars",
    (await v.eval(`document.querySelector('[role=radio][aria-checked=true]')?.getAttribute('aria-label')`)) === "5 — Very satisfied");
  await v.eval(`document.querySelector("textarea").focus()`);
  await v.send("Input.insertText", { text: "Sorted the same day, thank you." });
  await v.click('button[type="submit"]');
  const recorded = await waitFor(v, `!!document.querySelector("[data-csat-recorded]")`, SLOW);
  check("the rating submits and the thanks state shows", recorded);
  check("the visitor stays on the survey (no sign-in redirect)",
    (await v.eval("location.pathname")) === `/public/csat/${encodeURIComponent(token)}`);
  const answer = await a.eval(`(async () => { ${PAGE_API} return api("GET", "/items/" + ${JSON.stringify(world.itemId)} + "/csat"); })()`);
  check("GET /items/{id}/csat returns the visitor's rating and comment",
    answer.status === 200 && answer.body?.rating === 5 && answer.body?.comment === "Sorted the same day, thank you.", JSON.stringify(answer));
  await v.screenshot(resolve(TMP, "csat-mail-plugins-proof-survey.png"));
  check("no console errors (visitor)", v.consoleErrors.length === 0, JSON.stringify(v.consoleErrors.slice(0, 3)));

  // 4. The mailed bodies, signed in.
  await a.navigate(`${baseUrl}/issues/${world.itemKey}`, 2500);
  const folded = await waitFor(a, `!!document.querySelector('[data-mail-signed=${JSON.stringify(world.commentId)}]')
    && !!document.querySelector('[data-mail-signed=${JSON.stringify(world.itemId)}]')`, SLOW);
  check("the description and the comment read with their signatures folded", folded,
    await a.eval(`document.querySelector("main")?.innerText.slice(0, 300)`));
  const fromMail = await a.eval(`performance.getEntriesByType("resource").map((e) => new URL(e.name).pathname).includes("/plugins/mailintake/remoteEntry.js")`);
  check("the fold is the mailintake remote's (/plugins/mailintake/remoteEntry.js)", fromMail);
  const hidden = await a.eval(`({ comment: document.body.innerText.includes("Floor 3 reception"),
    description: document.body.innerText.includes("Kind regards"), above: document.body.innerText.includes("Still jamming after the fix.") })`);
  check("the text above each signature reads and the signatures are hidden",
    hidden.above && !hidden.comment && !hidden.description, JSON.stringify(hidden));
  const selector = `[data-mail-signed=${JSON.stringify(world.commentId)}]`;
  await a.eval(`document.querySelector('${selector} summary').scrollIntoView({ block: "center" })`);
  await a.click(`${selector} summary`);
  const shown = await waitFor(a, `document.body.innerText.includes("Floor 3 reception")`, SLOW);
  check("Show signature unfolds it", shown);
  await a.eval(`document.querySelector('${selector} summary').scrollIntoView({ block: "center" })`);
  await sleep(200);
  await a.screenshot(resolve(TMP, "csat-mail-plugins-proof-signature.png"));
  await a.eval(`Array.from(document.querySelectorAll('${selector} button')).find((b) => b.textContent.trim() === "Not a signature").click()`);
  const plain = await waitFor(a, `!document.querySelector('${selector}') && document.body.innerText.includes("Floor 3 reception")`, SLOW);
  check("Not a signature: the comment reads whole", plain);
  const after = await a.eval(`(async () => { ${PAGE_API} return api("GET", "/items/" + ${JSON.stringify(world.itemId)} + "/comments"); })()`);
  const row = (after.body ?? []).find((c) => c.id === world.commentId);
  check("…and the server dropped the annotation, keeping the body", row && row.email_signature === null && row.body.endsWith(COMMENT_SIGNATURE),
    JSON.stringify(row && { email_signature: row.email_signature }));
  check("the description stays folded (its own annotation)", await a.eval(`!!document.querySelector('[data-mail-signed=${JSON.stringify(world.itemId)}]')`));
  check("no console errors (agent)", a.consoleErrors.length === 0, JSON.stringify(a.consoleErrors.slice(0, 3)));
} finally {
  // 5. Clean up: the survey, the comment and the issue go with the project.
  if (world?.projectId) {
    const cleaned = await agent.session.eval(`(async () => { ${PAGE_API}
      const p = await api("DELETE", "/projects/" + ${JSON.stringify(world.projectId)});
      const gone = await api("GET", "/projects/" + ${JSON.stringify(world.projectId)});
      return [p.status, gone.status];
    })()`);
    check("the project is deleted again", cleaned.join() === "204,404", JSON.stringify(cleaned));
  }
  await visitor?.close();
  await agent.close();
}
const failed = report(checks, { proof: "csat survey page + mailed bodies (RADD-1401)", project: key });
process.exit(failed ? 1 : 0);
