/**
 * Proof for inline comments (RADD-726 and its subtasks).
 *
 * What the issue's done-when actually asks for:
 *   1. commenting on a selection puts a highlight on that sentence and a thread
 *      beside it;
 *   2. the thread stays put when an UNRELATED paragraph elsewhere is edited —
 *      the whole reason the anchor is a quote and not an offset;
 *   3. resolving clears the highlight and the rail entry but leaves it readable.
 * Editing the quoted sentence away (the rail's Detached group, RADD-1276) is
 * page-detached-comments-proof.mjs's.
 *
 * Highlights are painted with the CSS Custom Highlight API, which puts nothing
 * in the DOM — so (1) and (3) are asserted against `CSS.highlights`, not against
 * markup.
 *
 * Usage: node scripts/inline-comments-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep, waitFor } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);

const QUOTE = "The cache is invalidated on write";
const BODY_V1 = `# Design\n\nIntro paragraph that stays put.\n\n${QUOTE} and never on read.\n\nA closing note.\n`;
// An edit ABOVE the anchor: the quoted sentence itself is untouched.
const BODY_V2 = `# Design\n\nIntro paragraph that stays put.\n\nAn entirely new section inserted above.\n\n${QUOTE} and never on read.\n\nA closing note.\n`;

async function main() {
  const { session, close } = await openBrowser({
    port: 9451, profile: resolve(process.env.TMPDIR || "/tmp", "radd-inline-proof"), height: 1200, scale: 1,
  });
  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const page = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    let row = pages.find((p) => p.slug === "inline-proof");
    if (!row) {
      row = await (await fetch("/api/v1/pages", { method: "POST", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Inline proof", slug: "inline-proof",
                               body: ${JSON.stringify(BODY_V1)} }) })).json();
    } else {
      await fetch("/api/v1/pages/" + row.id, { method: "PATCH", credentials: "include",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({ body: ${JSON.stringify(BODY_V1)} }) });
      // Clear comments left by an earlier run.
      const existing = await (await fetch("/api/v1/page/" + row.id + "/comments", {credentials:"include"})).json();
      for (const c of existing) {
        await fetch("/api/v1/comments/" + c.id, { method: "DELETE", credentials: "include" });
      }
    }
    return { id: row.id, slug: row.slug };
  })()`);

  const openPage = async () => {
    await session.navigate(`${baseUrl}/pages/${spaceSlug}/${page.slug}`, 0);
    for (let i = 0; i < 40; i++) {
      await sleep(500);
      const ready = await session.eval(
        `(() => { const b = document.querySelector('[data-page-body]'); return !!b && (b.textContent||"").includes("closing note"); })()`);
      if (ready) return;
    }
    throw new Error("page body never rendered");
  };

  // The rail loads its comments after the page renders; on a real instance that lands later than
  // the body, so a probe taken early reads "Loading comments…" and no threads at all.
  // …and each card's footer (Reply / Resolve) follows the permission read, so wait for it too:
  // every open thread card must carry its Reply action before the rail counts as settled.
  const railSettled = () => waitFor(session, `(() => {
    const rail = document.querySelector('[data-inline-comment-rail]'); if (!rail) return false;
    if ((rail.textContent || '').includes('Loading comments')) return false;
    return [...rail.querySelectorAll('[data-thread]')].every((card) => card.dataset.thread === 'resolved' || card.querySelector('[data-open-reply]'));
  })()`, { attempts: 60 });
  const probe = async () => (await railSettled(), session.eval(`(() => {
    const rail = document.querySelector('[data-inline-comment-rail]');
    const highlight = CSS.highlights.get("radd-inline-comment");
    return {
      supported: "highlights" in CSS,
      highlighted: highlight ? highlight.size : 0,
      // The text each painted range actually covers — this is what proves the
      // highlight is on the right sentence rather than merely present.
      highlightedText: highlight ? [...highlight].map((r) => r.toString()) : [],
      threads: rail ? rail.querySelectorAll('[data-thread]').length : 0,
      railText: rail ? (rail.textContent || "").replace(/\\s+/g, " ") : "",
      resolvedToggle: rail ? /Resolved \\(\\d+\\)/.test(rail.textContent || "") : false,
      // RADD-1448: Reply is an action on every card; the disclosure exists only over replies.
      replyActions: rail ? rail.querySelectorAll('[data-thread] [data-open-reply]').length : 0,
      disclosures: rail ? rail.querySelectorAll('[data-thread] [data-thread-toggle]').length : 0,
    };
  })()`));

  await openPage();

  // Post the inline comment through the API with an anchor built the same way
  // the selection popover builds one — the UI path for SELECTING text is
  // exercised separately below; this keeps the anchor deterministic.
  await session.eval(`(async () => {
    const body = document.querySelector('[data-page-body]');
    const text = body.textContent;
    const at = text.indexOf(${JSON.stringify(QUOTE)});
    await fetch("/api/v1/page/${page.id}/comments", {
      method: "POST", credentials: "include", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        body: "Is this still true after the rewrite?",
        anchor: { quote: ${JSON.stringify(QUOTE)},
                  prefix: text.slice(Math.max(0, at - 32), at),
                  suffix: text.slice(at + ${QUOTE.length}, at + ${QUOTE.length} + 32) },
      }),
    });
  })()`);

  await openPage();
  const afterPost = await probe();

  // (2) Edit an UNRELATED paragraph above it.
  await session.eval(`(async () => {
    await fetch("/api/v1/pages/${page.id}", { method: "PATCH", credentials: "include",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({ body: ${JSON.stringify(BODY_V2)} }) });
  })()`);
  await openPage();
  const afterEditAbove = await probe();

  // (3) Resolve it.
  await session.eval(`(async () => {
    const list = await (await fetch("/api/v1/page/${page.id}/comments", {credentials:"include"})).json();
    await fetch("/api/v1/comments/" + list[0].id + "/resolve", {method:"POST", credentials:"include"});
  })()`);
  await openPage();
  const afterResolve = await probe();

  // RADD-731: selecting text in the body offers a Comment affordance.
  const selection = await session.eval(`(() => {
    const body = document.querySelector('[data-page-body]');
    // Whatever element Crepe rendered that line into — asserting on <p> made
    // this throw rather than fail, which hides the real result.
    const node = [...body.querySelectorAll('*')]
      .filter((e) => (e.textContent || "").includes("closing note"))
      .pop();
    if (!node) return false;
    const range = document.createRange();
    range.selectNodeContents(node);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return true;
  })()`);
  await sleep(500);
  const popover = await session.eval(
    `!![...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Comment")`);

  const hoverCapable = await session.hoverCapable();
  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the highlight API is available": afterPost.supported === true,
    "commenting highlights the quoted sentence": afterPost.highlighted === 1,
    "and the highlight covers the right words":
      (afterPost.highlightedText[0] || "").includes(QUOTE),
    "a thread appears beside it": afterPost.railText.includes("Is this still true"),
    "it offers Reply as an action, with no disclosure over no replies":
      afterPost.threads === 1 && afterPost.replyActions === 1 && afterPost.disclosures === 0,
    // The reason the anchor is a quote and not an offset.
    "an edit ABOVE leaves it anchored": afterEditAbove.highlighted === 1,
    "still on the same sentence":
      (afterEditAbove.highlightedText[0] || "").includes(QUOTE),
    "resolving clears the highlight": afterResolve.highlighted === 0,
    "and leaves it readable behind a toggle": afterResolve.resolvedToggle === true,
    "selecting text offers a Comment affordance": selection && popover === true,
    "no console errors": session.consoleErrors.length === 0,
  };
  const failed = report(checks, { afterPost, afterEditAbove, afterResolve, popover, consoleErrors: session.consoleErrors });
  await close();
  return failed;
}

main()
  .then((f) => process.exit(f ? 1 : 0))
  .catch((e) => { console.error(e); process.exit(2); });
