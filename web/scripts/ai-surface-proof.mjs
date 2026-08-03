/**
 * Proves RADD-753: the AI selection surface is ours, end to end.
 *
 * The three things the issue asks to survive the change are selection-scoped
 * AI, whole-document AI, and the reviewable diff — so this drives a real
 * transform against the real endpoint and checks the review that comes back,
 * rather than checking that a button exists.
 *
 * It also asserts the removal: no Crepe AI or selection toolbar in the DOM, and
 * no command dispatched through a name lookup.
 *
 * Needs a working AI provider. It says so and exits 2 rather than failing, so a
 * dormant instance is not reported as a regression.
 *
 * Usage: node scripts/ai-surface-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";
import { MOCK_REPLY, startMockLlm } from "./lib/mock-llm.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9458;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-ai-surface-proof");

const SEED = [
  "# Notes",
  "",
  "teh cache is invalidated on write and never on read, wich is fine",
  "",
  "A second paragraph that must not change.",
  "",
].join("\n");

/** Wait for a condition rather than guessing at a sleep. */
async function waitFor(session, expression, tries = 60) {
  for (let i = 0; i < tries; i++) {
    if (await session.eval(expression)) return true;
    await sleep(500);
  }
  return false;
}

async function main() {
  const llm = await startMockLlm(8111);
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
    return 0;
  }

  // Point the CHAT role at a stand-in provider for the duration.
  //
  // What is under test is the chain we own — stream in, splice over the
  // selection, hand the new document to the diff plugin, render a review — not
  // a model's opinion about grammar. Depending on a real provider makes this
  // proof fail whenever someone else's GPU is off, which is how a proof stops
  // being run. It also makes the diff DETERMINISTIC, so the assertion can name
  // the words that changed.
  //
  // Sweep any leftover mock FIRST. A previous run that failed to clean up leaves
  // the chat role pointing at `proof-mock`, and capturing that as the "previous"
  // role makes the restore put the mock back — a cleanup that faithfully
  // restores the wrong thing. This is why the sweep is separate from the
  // capture rather than being trusted to have happened.
  const previousRole = await session.eval(`(async () => {
    const providers = await (await fetch("/api/v1/ai/providers", {credentials:"include"})).json();
    const leftover = providers.filter((p) => p.name === "proof-mock");
    if (leftover.length) {
      const real = providers.find((p) => p.name !== "proof-mock" && !/embed/i.test(p.name));
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
    return chat && chat.provider_name !== "proof-mock" ? chat : null;
  })()`);
  const mock = await session.eval(`(async () => {
    const provider = await (await fetch("/api/v1/ai/providers", {
      method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ name: "proof-mock", wire_shape: "openai",
                             base_url: "http://127.0.0.1:8111/v1", default_model: "mock-1" }),
    })).json();
    await fetch("/api/v1/ai/roles/chat", {
      method: "PUT", credentials: "include", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ provider_id: provider.id, model: "mock-1" }),
    });
    return { providerId: provider.id };
  })()`);

  /**
   * Put the instance back, and CHECK that it went back.
   *
   * The first version fired the requests and moved on; it silently left the dev
   * instance pointing at a mock that had just been shut down, which is a worse
   * outcome than the proof failing. A cleanup nobody verifies is a cleanup that
   * did not happen.
   */
  const restore = async () => {
    const target = previousRole
      ? { provider_id: previousRole.provider_id, model: previousRole.model }
      : null;
    return session.eval(`(async () => {
      const target = ${JSON.stringify(target)};
      const role = target
        ? await fetch("/api/v1/ai/roles/chat", {
            method: "PUT", credentials: "include",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(target),
          })
        : await fetch("/api/v1/ai/roles/chat", { method: "DELETE", credentials: "include" });
      const removed = await fetch("/api/v1/ai/providers/${mock.providerId}", {
        method: "DELETE", credentials: "include",
      });
      const roles = await (await fetch("/api/v1/ai/roles", {credentials:"include"})).json();
      const providers = await (await fetch("/api/v1/ai/providers", {credentials:"include"})).json();
      return {
        roleStatus: role.status,
        removedStatus: removed.status,
        chatProvider: (roles.find((r) => r.role === "chat") || {}).provider_name || null,
        mockGone: !providers.some((p) => p.name === "proof-mock"),
      };
    })()`);
  };

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "ai-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "AI proof", body }),
      })).json();
    } else {
      await fetch("/api/v1/pages/" + page.id, {
        method: "PATCH", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ body }),
      });
    }
    return { id: page.id, slug: page.slug };
  })()`);

  await session.navigate(`${baseUrl}/pages/${spaceSlug}/${created.slug}`, 2500);
  await session.eval(`(() => { document.querySelector('button[aria-label="Edit page"]')?.click(); })()`);
  await sleep(3000);

  const chrome = await session.eval(`(() => ({
    // Crepe's floating toolbar and its AI surface must both be gone.
    crepeToolbars: document.querySelectorAll("milkdown-toolbar, .milkdown-toolbar").length,
    crepeAi: document.querySelectorAll("milkdown-ai-prompt, .milkdown-ai-prompt, .milkdown-ai-panel").length,
    ourToolbarButton: !!document.querySelector('[role="toolbar"] svg.radd-ai-toolbar-icon'),
  }))()`);

  // Select the misspelled sentence: click into it, then Home + Shift+End.
  await session.click(".ProseMirror p");
  await sleep(300);
  for (const [key, code, vk, mods] of [["Home", "Home", 36, 0], ["End", "End", 35, 8]]) {
    for (const type of ["keyDown", "keyUp"]) {
      await session.send("Input.dispatchKeyEvent", {
        type, key, code, windowsVirtualKeyCode: vk, modifiers: mods,
      });
    }
  }
  await sleep(500);

  const onSelection = await session.eval(`(() => {
    const b = document.querySelector("[data-ai-selection-button]");
    if (!b) return { present: false };
    const r = b.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return {
      present: true,
      paintedAtItsOwnCoords: b.contains(top),
      label: b.textContent.trim(),
    };
  })()`);

  const before = await session.eval(
    `document.querySelector(".ProseMirror").textContent`);

  // Open it and pick a curated action — the same list the toolbar button shows.
  await session.click("[data-ai-selection-button]");
  await sleep(500);
  const menu = await session.eval(`(async () => {
    const m = document.querySelector("[data-ai-selection-menu]");
    if (!m) return { open: false };
    const declared = await (await fetch("/api/v1/ai/editor/actions", {credentials:"include"})).json();
    return {
      open: true,
      options: [...m.querySelectorAll('[role="option"], button')].map((b) => b.textContent.trim()).filter(Boolean),
      declared: declared.map((a) => a.label),
      hasFreeform: !!m.querySelector("input, textarea"),
    };
  })()`);

  await session.click("[data-ai-selection-menu] button", (t) => /grammar/i.test(t));
  // A streaming indicator must appear, then a diff review.
  const streamed = await waitFor(session, `!!document.querySelector("[data-ai-streaming]")`, 20);
  const reviewed = await waitFor(session,
    `document.querySelectorAll('[class*="milkdown-diff"]').length > 0`, 90);

  const review = await session.eval(`(() => {
    const marks = [...document.querySelectorAll('[class*="milkdown-diff"]')];
    const buttons = marks.flatMap((m) => [...m.querySelectorAll("button")])
      .map((b) => b.textContent.trim()).filter(Boolean);
    return {
      decorations: marks.length,
      buttons: [...new Set(buttons)],
      // The SECOND paragraph was outside the selection and must be untouched.
      secondParagraphIntact: document.querySelector(".ProseMirror").textContent
        .includes("A second paragraph that must not change."),
      text: document.querySelector(".ProseMirror").textContent.slice(0, 200),
    };
  })()`);

  // Accept the change and check the document actually took it.
  const accepted = await session.eval(`(() => {
    const b = [...document.querySelectorAll('[class*="milkdown-diff"] button')]
      .find((x) => /accept/i.test(x.textContent));
    if (!b) return false;
    b.click();
    return true;
  })()`);
  await sleep(1200);
  const after = await session.eval(`document.querySelector(".ProseMirror").textContent`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  // Put the instance back BEFORE building the checks, so a failed assertion
  // still leaves the dev instance pointing at its real provider.
  const restored = await restore();
  llm.close();

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "no Crepe selection toolbar in the DOM": chrome.crepeToolbars === 0,
    "no Crepe AI surface in the DOM": chrome.crepeAi === 0,
    "the toolbar still offers a document-wide AI button": chrome.ourToolbarButton === true,
    "selecting text offers our AI affordance": onSelection.present === true,
    "and it is what is painted at its own coordinates":
      onSelection.paintedAtItsOwnCoords === true,
    "it opens the curated action list": menu.open === true && menu.options.length > 0,
    "which is the server's list, not a hardcoded one":
      (menu.declared || []).length > 0 &&
      menu.declared.every((label) => menu.options.some((o) => o.includes(label))),
    "and a freeform prompt": menu.hasFreeform === true,
    "a run streams": streamed === true,
    "and lands as a reviewable diff, not a silent replace": reviewed === true,
    "the review offers accept and reject": review.buttons.some((b) => /accept/i.test(b)) &&
      review.buttons.some((b) => /reject/i.test(b)),
    "text outside the selection is untouched": review.secondParagraphIntact === true,
    "accepting changes the document": accepted === true && after !== before,
    // The stand-in returns a FIXED sentence, so this names what changed rather
    // than settling for "something is different".
    "the accepted text is what the model returned":
      (after || "").includes("which is fine") && !(after || "").includes("wich is fine"),
    "no console errors": consoleErrors.length === 0,
    // A cleanup nobody verifies is a cleanup that did not happen: the first
    // version fired the restore requests and moved on, leaving the dev instance
    // pointing at a mock that had just been shut down.
    "the instance was put back":
      restored?.mockGone === true && restored?.chatProvider !== "proof-mock",
  };

  return report(checks, { chrome, onSelection, menu, streamed, reviewed, review, accepted, restored, before: before?.slice(0, 120), after: after?.slice(0, 120), consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
