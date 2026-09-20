/**
 * RADD-1276: inline comments whose passage is gone sit under a Detached
 * heading with a plain label, one action resolves them all, and a resolved
 * one keeps its quote.
 *
 * A page gets three anchored comments; its body is then rewritten so the first
 * passage stays, the second is gone, and the third now appears twice with the
 * same context (ambiguous). Expected: Open holds one card with no label,
 * Detached (2) holds "Passage removed" and "Passage ambiguous", Resolve all
 * (after its confirm) resolves both, and Resolved (2) still shows both quotes.
 *
 *   node scripts/page-detached-comments-proof.mjs [baseUrl] [email] [password]
 */
import { mkdir } from "node:fs/promises";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const baseUrl = process.argv[2] || process.env.RADD_PROOF_BASE_URL || "http://127.0.0.1:8000";
const email = process.argv[3] || process.env.RADD_PROOF_EMAIL || "admin@example.com";
const password = process.argv[4] || process.env.RADD_PROOF_PASSWORD || "change-me";
const output = process.env.RADD_PROOF_OUTPUT_DIR || "/tmp/radd-detached-comments-proof";

const P1 = "The cache is invalidated on write and never on read.";
const P2 = "Deploys happen on Tuesday after the standup.";
const P3 = "Rollbacks are a config change, not a redeploy.";
const BEFORE = `# Runbook\n\n${P1}\n\n${P2}\n\n${P3}\n`;
// P1 survives; P2 is gone; P3 appears twice with identical context.
const AFTER = `# Runbook\n\n${P1}\n\nA new paragraph about something else.\n\n${P3}\n\n${P3}\n`;

async function waitFor(session, expression, tries = 40) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(500);
  }
  return false;
}

async function main() {
  await mkdir(output, { recursive: true });
  const { session, close } = await openBrowser({ port: 9535, profile: output + "/chrome", width: 1440, height: 1100 });
  const checks = {};
  const api = (expression) => session.eval(`(async () => { ${expression} })()`);
  let page = null;
  try {
    await session.navigate(baseUrl + "/login", 1200);
    checks.loggedIn = (await session.login(baseUrl, email, password)) === 204;
    checks.hoverCapable = await session.hoverCapable();

    page = await api(`
      const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
      const space = spaces[0];
      const page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Detached comments proof " + Date.now().toString(36), body: ${JSON.stringify(BEFORE)} }),
      })).json();
      const comment = async (quote, prefix, suffix) => (await (await fetch("/api/v1/page/" + page.id + "/comments", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: "Still true?", anchor: { quote, prefix, suffix } }),
      })).json()).id;
      const kept = await comment("invalidated on write", "The cache is ", " and never on read");
      const removed = await comment("happen on Tuesday", "Deploys ", " after the standup");
      const ambiguous = await comment("a config change", "Rollbacks are ", ", not a redeploy");
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body: ${JSON.stringify(AFTER)} }),
      });
      return { id: page.id, slug: page.slug, space: space.slug, kept, removed, ambiguous };`);
    checks.seeded = Boolean(page?.id && page.kept && page.removed && page.ambiguous);

    await session.navigate(`${baseUrl}/pages/${page.space}/${page.slug}`, 2500);
    checks.railLoaded = await waitFor(session, `!!document.querySelector("[data-inline-comment-rail] [data-thread]")`, 30);
    await sleep(800);
    const rail = await session.eval(`(() => {
      const rail = document.querySelector("[data-inline-comment-rail]");
      const group = document.querySelector("[data-detached-comments]");
      const cardOf = (id) => rail.querySelector('[data-thread][data-comment-id="' + id + '"]');
      const label = (id) => cardOf(id)?.querySelector("[data-orphan-label]")?.textContent?.trim() ?? null;
      return {
        heading: rail.querySelector("h2")?.textContent,
        groupHeading: group?.querySelector("h3")?.textContent ?? null,
        keptInOpen: !!cardOf(${JSON.stringify(page.kept)}) && !group?.contains(cardOf(${JSON.stringify(page.kept)})),
        keptLabel: label(${JSON.stringify(page.kept)}),
        removedInGroup: !!group?.contains(cardOf(${JSON.stringify(page.removed)})),
        removedLabel: label(${JSON.stringify(page.removed)}),
        ambiguousInGroup: !!group?.contains(cardOf(${JSON.stringify(page.ambiguous)})),
        ambiguousLabel: label(${JSON.stringify(page.ambiguous)}),
        resolveAll: [...(group?.querySelectorAll("button") ?? [])].map((b) => b.textContent.trim()).find((t) => /^Resolve all$/.test(t)) ?? null,
        oldFootnote: /no longer match the page text/.test(rail.textContent),
      };
    })()`);
    checks.headingCountsAllOpen = rail.heading === "Inline comments (3)";
    checks.detachedGroupOfTwo = rail.groupHeading === "Detached (2)";
    checks.locatedCardStaysOpenWithoutLabel = rail.keptInOpen && rail.keptLabel === null;
    checks.removedCardLabelled = rail.removedInGroup && rail.removedLabel === "Passage removed";
    checks.ambiguousCardLabelled = rail.ambiguousInGroup && rail.ambiguousLabel === "Passage ambiguous";
    checks.resolveAllOffered = rail.resolveAll === "Resolve all";
    checks.oldFootnoteGone = rail.oldFootnote === false;
    await session.screenshot(output + "/detached.png");

    // --- one action, one confirm
    await session.click("[data-detached-comments] button", (t) => t.trim() === "Resolve all");
    checks.confirmAsked = await waitFor(session, `!!document.querySelector("[role=dialog]") && /Resolve these 2 comments/.test(document.querySelector("[role=dialog]").textContent)`, 10);
    await session.screenshot(output + "/confirm.png");
    await session.click("[role=dialog] button", (t) => t.trim() === "Resolve 2");
    checks.groupGoneAfterResolve = await waitFor(session, `!document.querySelector("[data-detached-comments]")`, 20);
    checks.resolvedToggleShowsTwo = await waitFor(session, `[...document.querySelectorAll("[data-inline-comment-rail] button")].some((b) => b.textContent.trim() === "Resolved (2)")`, 20);
    await session.click("[data-inline-comment-rail] button", (t) => t.trim() === "Resolved (2)");
    await sleep(500);
    const resolvedCards = await session.eval(`(() => {
      const cards = [...document.querySelectorAll("[data-inline-comment-rail] [data-thread]")];
      const quoteOf = (id) => cards.find((c) => c.dataset.commentId === id)?.textContent ?? "";
      return {
        removedKeepsQuote: /happen on Tuesday/.test(quoteOf(${JSON.stringify(page.removed)})),
        ambiguousKeepsQuote: /a config change/.test(quoteOf(${JSON.stringify(page.ambiguous)})),
      };
    })()`);
    checks.resolvedRemovedKeepsQuote = resolvedCards.removedKeepsQuote;
    checks.resolvedAmbiguousKeepsQuote = resolvedCards.ambiguousKeepsQuote;
    await session.screenshot(output + "/resolved.png");
    const state = await api(`
      const feed = await (await fetch("/api/v1/page/${page.id}/comments/feed?section=inline&limit=50", {credentials:"include"})).json();
      const rows = feed.comments ?? [];
      const by = (id) => rows.find((r) => r.id === id) ?? {};
      return { kept: !!by(${JSON.stringify(page.kept)}).resolved_at, removed: !!by(${JSON.stringify(page.removed)}).resolved_at, ambiguous: !!by(${JSON.stringify(page.ambiguous)}).resolved_at };`);
    checks.apiResolvedExactlyTheDetached = state.kept === false && state.removed === true && state.ambiguous === true;
    checks.noConsoleErrors = session.consoleErrors.length === 0;
    if (!checks.noConsoleErrors) console.error(session.consoleErrors);
    return report(checks, { rail, state });
  } finally {
    if (page) {
      try {
        await api(`await fetch("/api/v1/pages/${page.id}", { method: "DELETE", credentials: "include" }); return true;`);
      } catch (error) {
        console.error("teardown failed:", error);
      }
    }
    await close();
  }
}

process.exitCode = await main();
