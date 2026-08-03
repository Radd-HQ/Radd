/**
 * Proves RADD-762: an AI run says what it is doing, and a review has one way out.
 *
 * The bug this guards is a positioning bug that a screenshot at the wrong moment
 * would have missed and a build could never catch: the progress indicator was
 * positioned off the SELECTION rect, so a document-wide run (the toolbar button,
 * and the read-mode hand-off that is "Summarize" in edit mode) painted it at
 * `x: -110` — present in the DOM, correct in every unit sense, and off the left
 * edge of the screen. So the first assertion here is not "an indicator exists",
 * it is "its rectangle is inside the viewport and it is what is painted there".
 *
 * It then drives the three exits a review has to offer — Stop mid-stream,
 * Reject all, Accept all — against the DOCUMENT, because the point of accept-all
 * is that it applies every change and the point of reject-all is that it applies
 * none. Counting buttons would prove neither.
 *
 * The transform runs against a stand-in provider (see lib/mock-llm.mjs) so the
 * diff is deterministic and this does not fail whenever someone else's GPU is
 * off. Needs AI editor actions enabled; says so and exits 0 if they are not.
 *
 * Usage: node scripts/ai-feedback-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";
import { startMockLlm } from "./lib/mock-llm.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9461;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ai-feedback-proof");

// Three changed paragraphs, so "Accept all" has something to be worth pressing
// and the per-paragraph pairs are the wall the issue describes.
const SEED = [
  "# Notes",
  "",
  "teh cache is invalidated on write and never on read, wich is fine",
  "",
  "A second paragraph with erors in it.",
  "",
  "A third paragraph that alsoo has a problem.",
  "",
].join("\n");

const REPLY = [
  "# Notes",
  "",
  "The cache is invalidated on write and never on read, which is fine.",
  "",
  "A second paragraph with errors in it.",
  "",
  "A third paragraph that also has a problem.",
].join("\n");

/** The words the reply fixes — named, so "the document changed" isn't enough. */
const FIXED = ["which is fine", "with errors in it", "that also has a problem"];
const BROKEN = ["wich is fine", "erors in it", "alsoo has a problem"];

/** Wait for a condition rather than guessing at a sleep. */
async function waitFor(session, expression, tries = 60) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(250);
  }
  return false;
}

/** Toast text on screen — the Toaster is the only role=status that is aria-live. */
const TOASTS = `[...document.querySelectorAll('[role="status"][aria-live="polite"] span')]
  .map((s) => s.textContent.trim())`;

const PANEL = `document.querySelector("[data-ai-run-panel]")`;

/** Two rectangles intersect. Injected into the page beside each measurement. */
const OVERLAPS = `const overlaps = (a, b) =>
  !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);`;

/** Open the toolbar's AI menu and pick the grammar action — a run over the WHOLE
 *  document, which is the scope that had no visible progress at all. */
async function startDocumentRun(session) {
  await session.click('[role="toolbar"] button[aria-label="AI"]');
  await sleep(400);
  await session.click("[data-ai-toolbar-menu] button", (t) => /grammar/i.test(t));
}

async function main() {
  const llm = await startMockLlm(8113, REPLY);
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const ready = await session.eval(`(async () => {
    const status = await (await fetch("/api/v1/ai/status", {credentials:"include"})).json();
    return status?.features?.editor_actions === true;
  })()`);
  if (!ready) {
    console.error("AI editor actions are not enabled on this instance — skipping.");
    llm.close();
    return 0;
  }

  // Point the chat role at the stand-in, sweeping any leftover from a failed
  // run FIRST — capturing a leftover as "previous" makes the restore faithfully
  // put the mock back. (Same reasoning as ai-surface-proof; same code.)
  const previousRole = await session.eval(`(async () => {
    const providers = await (await fetch("/api/v1/ai/providers", {credentials:"include"})).json();
    const leftover = providers.filter((p) => p.name === "feedback-proof-mock");
    if (leftover.length) {
      const real = providers.find((p) => p.name !== "feedback-proof-mock" && !/embed/i.test(p.name));
      if (real) {
        await fetch("/api/v1/ai/roles/chat", {
          method: "PUT", credentials: "include",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ provider_id: real.id, model: real.default_model || "" }),
        });
      }
      for (const p of leftover) {
        await fetch("/api/v1/ai/providers/" + p.id, { method: "DELETE", credentials: "include" });
      }
    }
    const roles = await (await fetch("/api/v1/ai/roles", {credentials:"include"})).json();
    const chat = roles.find((r) => r.role === "chat") ?? null;
    return chat && chat.provider_name !== "feedback-proof-mock" ? chat : null;
  })()`);
  const mock = await session.eval(`(async () => {
    const provider = await (await fetch("/api/v1/ai/providers", {
      method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name: "feedback-proof-mock", wire_shape: "openai",
                             base_url: "http://127.0.0.1:8113/v1", default_model: "mock-1" }),
    })).json();
    await fetch("/api/v1/ai/roles/chat", {
      method: "PUT", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ provider_id: provider.id, model: "mock-1" }),
    });
    return { providerId: provider.id };
  })()`);

  const restore = async () => {
    const target = previousRole
      ? { provider_id: previousRole.provider_id, model: previousRole.model }
      : null;
    return session.eval(`(async () => {
      const target = ${JSON.stringify(target)};
      await (target
        ? fetch("/api/v1/ai/roles/chat", {
            method: "PUT", credentials: "include",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(target),
          })
        : fetch("/api/v1/ai/roles/chat", { method: "DELETE", credentials: "include" }));
      await fetch("/api/v1/ai/providers/${mock.providerId}", {
        method: "DELETE", credentials: "include",
      });
      const roles = await (await fetch("/api/v1/ai/roles", {credentials:"include"})).json();
      const providers = await (await fetch("/api/v1/ai/providers", {credentials:"include"})).json();
      return {
        chatProvider: (roles.find((r) => r.role === "chat") || {}).provider_name || null,
        mockGone: !providers.some((p) => p.name === "feedback-proof-mock"),
      };
    })()`);
  };

  const seedPage = () => session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "ai-feedback-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "AI feedback proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  const created = await seedPage();
  const openEditor = async () => {
    await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
    await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
    await sleep(2500);
  };
  await openEditor();

  const docText = () => session.eval(`document.querySelector(".ProseMirror").textContent`);
  const before = await docText();

  // ---------------------------------------------------------------- run 1: Stop
  await startDocumentRun(session);
  const panelAppeared = await waitFor(session, `!!${PANEL}`, 40);

  // The whole bug, measured: where is it, and is it what gets painted there?
  const placement = await session.eval(`(() => {
    ${OVERLAPS}
    const p = ${PANEL};
    if (!p) return { present: false };
    const r = p.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + 16);
    return {
      present: true,
      rect: { left: r.left, top: r.top, right: r.right, bottom: r.bottom },
      viewport: { width: window.innerWidth, height: window.innerHeight },
      insideViewport: r.left >= 0 && r.top >= 0 &&
                      r.right <= window.innerWidth && r.bottom <= window.innerHeight,
      paintedAtItsOwnCoords: !!hit && p.contains(hit),
      overlapsDocument: overlaps(r, document.querySelector(".ProseMirror").getBoundingClientRect()),
      namesTheAction: /grammar/i.test(p.textContent || ""),
      saysWhatItIsDoing: /reading your text|writing the result/i.test(p.textContent || ""),
      streamingFlag: p.hasAttribute("data-ai-streaming"),
      hasStop: !!p.querySelector('button[aria-label="Stop"]'),
    };
  })()`);

  // The stream is visible as it arrives: sample the preview twice.
  const previewText = () =>
    session.eval(`(document.querySelector("[data-ai-run-preview]")?.textContent || "")`);
  const firstSample = await previewText();
  await sleep(400);
  const secondSample = await previewText();

  await session.click('[data-ai-run-panel] button[aria-label="Stop"]');
  await sleep(1500);
  const afterStop = await session.eval(`({
    panelGone: !${PANEL},
    toasts: ${TOASTS},
    docUnchanged: document.querySelector(".ProseMirror").textContent === ${JSON.stringify(before)},
    decorations: document.querySelectorAll('[class*="milkdown-diff"]').length,
  })`);

  // ---------------------------------------------------------- run 2: Reject all
  await startDocumentRun(session);
  const reviewOpened = await waitFor(session,
    `document.querySelectorAll(".milkdown-diff-controls").length > 0`, 120);

  const reviewing = await session.eval(`(() => {
    ${OVERLAPS}
    const p = ${PANEL};
    const pairs = document.querySelectorAll(".milkdown-diff-controls");
    const claimed = (p?.textContent || "").match(/(\\d+)\\s+changes? to review/);
    return {
      pairs: pairs.length,
      claimed: claimed ? Number(claimed[1]) : null,
      overlapsDocument: !!p &&
        overlaps(p.getBoundingClientRect(),
                 document.querySelector(".ProseMirror").getBoundingClientRect()),
      hasAcceptAll: [...(p?.querySelectorAll("button") || [])].some((b) => /accept all/i.test(b.textContent)),
      hasRejectAll: [...(p?.querySelectorAll("button") || [])].some((b) => /reject all/i.test(b.textContent)),
      // Still there, still reachable — quieter is not hidden.
      perBlockButtons: document.querySelectorAll(".milkdown-diff-controls button").length,
      perBlockDisabled: [...document.querySelectorAll(".milkdown-diff-controls button")]
        .filter((b) => b.disabled).length,
    };
  })()`);

  // The per-block pair at rest carries no chip; hovering its block brings it back.
  // Park the pointer first: it is still sitting wherever the last click left it,
  // and measuring a "rest" style under the cursor would prove nothing.
  await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 4, y: 4 });
  await sleep(200);
  const restStyle = await session.eval(`(() => {
    const b = document.querySelector(".milkdown-diff-controls button");
    if (!b) return null;
    const s = getComputedStyle(b);
    return { background: s.backgroundColor, border: s.borderTopColor, color: s.color };
  })()`);
  await session.hover(".radd-diff-new-block");
  await sleep(400);
  const hoverStyle = await session.eval(`(() => {
    const b = document.querySelector(".radd-diff-new-block .milkdown-diff-controls button");
    if (!b) return null;
    const s = getComputedStyle(b);
    return { background: s.backgroundColor, border: s.borderTopColor };
  })()`);

  await session.click("[data-ai-run-panel] button", (t) => /reject all/i.test(t));
  await sleep(1200);
  const afterReject = await session.eval(`({
    text: document.querySelector(".ProseMirror").textContent,
    decorations: document.querySelectorAll('[class*="milkdown-diff"]').length,
    panelGone: !${PANEL},
    toasts: ${TOASTS},
  })`);

  // ---------------------------------------------------------- run 3: Accept all
  await startDocumentRun(session);
  const secondReview = await waitFor(session,
    `document.querySelectorAll(".milkdown-diff-controls").length > 0`, 120);
  await session.click("[data-ai-run-panel] button", (t) => /accept all/i.test(t));
  await sleep(1500);
  const afterAccept = await session.eval(`({
    text: document.querySelector(".ProseMirror").textContent,
    decorations: document.querySelectorAll('[class*="milkdown-diff"]').length,
    panelGone: !${PANEL},
  })`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // Put the instance back BEFORE building the checks, so a failed assertion
  // still leaves the dev instance pointing at its real provider.
  const restored = await restore();
  await seedPage(); // leave the page as this proof found it
  llm.close();

  const transparent = (color) => /rgba\(.*,\s*0\)$/.test(color || "");

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "a document-wide run shows a panel": panelAppeared === true && placement.present === true,
    // The bug: it used to render at x = -110 for exactly this run.
    "the panel is inside the viewport": placement.insideViewport === true,
    "and it is what is painted at its own coordinates":
      placement.paintedAtItsOwnCoords === true,
    // A floating panel was tried first: anchored to the editor's bottom-right
    // it covered two of the three paragraphs of the diff it was asking about.
    "it does not cover the document it is describing":
      placement.overlapsDocument === false && reviewing.overlapsDocument === false,
    "it names the action being run": placement.namesTheAction === true,
    "and says what it is doing": placement.saysWhatItIsDoing === true,
    "it offers Stop": placement.hasStop === true,
    "the result is visible while it streams":
      secondSample.length > firstSample.length && secondSample.length > 0,
    "Stop ends the run": afterStop.panelGone === true,
    // Cancelling used to reject the run promise into the error toaster.
    "and does not report a failure": (afterStop.toasts || []).length === 0,
    "a stopped run leaves the document alone":
      afterStop.docUnchanged === true && afterStop.decorations === 0,

    "a finished run opens a review": reviewOpened === true && reviewing.pairs > 1,
    "the panel's change count is what is on screen": reviewing.claimed === reviewing.pairs,
    "the review offers Accept all and Reject all":
      reviewing.hasAcceptAll === true && reviewing.hasRejectAll === true,
    "per-block pairs survive it": reviewing.perBlockButtons === reviewing.pairs * 2 &&
      reviewing.perBlockDisabled === 0,
    "and are quiet at rest": transparent(restStyle?.background) && transparent(restStyle?.border),
    "until the block they belong to is hovered":
      hoverStyle !== null && !transparent(hoverStyle.background),

    "Reject all restores the original document": afterReject.text === before,
    "and clears the review": afterReject.decorations === 0 && afterReject.panelGone === true,
    "and reports no failure": (afterReject.toasts || []).length === 0,

    "Accept all takes every change in one click":
      secondReview === true &&
      FIXED.every((s) => (afterAccept.text || "").includes(s)) &&
      BROKEN.every((s) => !(afterAccept.text || "").includes(s)),
    "and clears the review too":
      afterAccept.decorations === 0 && afterAccept.panelGone === true,

    "no console errors": consoleErrors.length === 0,
    "the instance was put back":
      restored?.mockGone === true && restored?.chatProvider !== "feedback-proof-mock",
  };

  return report(checks, {
    placement, firstSample: firstSample.length, secondSample: secondSample.length,
    afterStop, reviewing, restStyle, hoverStyle, afterReject,
    afterAccept: { ...afterAccept, text: (afterAccept.text || "").slice(0, 160) },
    restored, consoleErrors,
  });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
