/**
 * Proves RADD-749: the editor's toolbar is ours.
 *
 * Three of these assertions are the issue's complaints, written as checks rather
 * than as prose:
 *
 *  - **it acts on click, not mousedown.** Crepe's items ran on `mousedown`, which
 *    silently passed a render proof against broken code and cannot be driven from
 *    a keyboard. So: press the mouse and do NOT release it — the document must be
 *    untouched. Then release, and it must change.
 *  - **active state is visible.** Crepe shipped no `.active` styling at all, which
 *    is why `rich-editor.css` retinted its bar. `aria-pressed` AND a computed
 *    background difference, because either alone can be true while the other is
 *    not.
 *  - **every control is reachable by keyboard.** Real buttons, no `tabindex=-1`,
 *    and Enter on a focused button runs it.
 *
 * Plus the removal itself: no editor may render Crepe's top bar.
 *
 * Usage: node scripts/editor-toolbar-proof.mjs <baseUrl> <spaceSlug> <email> <password>
 */
import { resolve } from "node:path";
import { HOVER_CAPABLE_PROBE, openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, spaceSlug, email, password] = process.argv.slice(2);
const PORT = 9454;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-toolbar-proof");

const SEED = "toolbar target paragraph\n";

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1100 });
  const { consoleErrors } = session;

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const created = await session.eval(`(async () => {
    const spaces = await (await fetch("/api/v1/page-spaces", {credentials:"include"})).json();
    const space = spaces.find((s) => s.slug === ${JSON.stringify(spaceSlug)});
    const pages = await (await fetch("/api/v1/page-spaces/" + space.id + "/pages", {credentials:"include"})).json();
    const body = ${JSON.stringify(SEED)};
    let page = pages.find((p) => p.slug === "toolbar-proof");
    if (!page) {
      page = await (await fetch("/api/v1/pages", {
        method: "POST", credentials: "include", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ space_id: space.id, title: "Toolbar proof", body }),
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

  const chrome = await session.eval(`(() => {
    const bar = document.querySelector('[role="toolbar"]');
    const controls = bar ? [...bar.querySelectorAll("button")] : [];
    return {
      ours: !!bar,
      crepeTopBars: document.querySelectorAll(".milkdown-top-bar").length,
      controlCount: controls.length,
      // Keyboard reachability: a real button with no negative tabindex.
      unreachable: controls
        .filter((b) => b.tabIndex < 0 || b.disabled)
        .map((b) => b.getAttribute("aria-label") || b.textContent.trim()),
      labels: controls.map((b) => b.getAttribute("aria-label")).filter(Boolean),
      // Everything the toolbar offers must be visible, not clipped off the row.
      barRect: bar ? bar.getBoundingClientRect().height : 0,
      overflowing: controls.filter((b) => {
        if (!bar) return false;
        const r = b.getBoundingClientRect(), br = bar.getBoundingClientRect();
        return r.bottom > br.bottom + 1 || r.right > br.right + 1;
      }).length,
    };
  })()`);

  // Put the cursor in the paragraph and select it all.
  await session.click(".ProseMirror p");
  await sleep(200);
  for (const type of ["keyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", {
      type, key: "a", code: "KeyA", windowsVirtualKeyCode: 65,
      modifiers: 2, // Ctrl
    });
  }
  await sleep(200);

  // --- press WITHOUT releasing: nothing may happen -------------------------
  const boldAt = await session.eval(`(() => {
    const b = document.querySelector('[role="toolbar"] button[data-toolbar-action="bold"]');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    const s = getComputedStyle(b);
    return { x: r.left + r.width / 2, y: r.top + r.height / 2,
             background: s.backgroundColor, pressed: b.getAttribute("aria-pressed") };
  })()`);
  await session.send("Input.dispatchMouseEvent", {
    type: "mousePressed", x: boldAt.x, y: boldAt.y, button: "left", clickCount: 1,
  });
  await sleep(400);
  const afterPressOnly = await session.eval(
    `document.querySelector(".ProseMirror").innerHTML.includes("<strong")`);

  // --- release: now it must act -------------------------------------------
  await session.send("Input.dispatchMouseEvent", {
    type: "mouseReleased", x: boldAt.x, y: boldAt.y, button: "left", clickCount: 1,
  });
  await sleep(500);
  const afterRelease = await session.eval(`(() => {
    const b = document.querySelector('[role="toolbar"] button[data-toolbar-action="bold"]');
    const s = getComputedStyle(b);
    return {
      bolded: document.querySelector(".ProseMirror").innerHTML.includes("<strong"),
      pressed: b.getAttribute("aria-pressed"),
      background: s.backgroundColor,
    };
  })()`);

  // --- keyboard: focus a control and press Enter ---------------------------
  const viaKeyboard = await session.eval(`(() => {
    const b = document.querySelector('[role="toolbar"] button[data-toolbar-action="quote"]');
    if (!b) return null;
    b.focus();
    return document.activeElement === b;
  })()`);
  for (const type of ["keyDown", "keyUp"]) {
    await session.send("Input.dispatchKeyEvent", {
      type, key: "Enter", code: "Enter", windowsVirtualKeyCode: 13,
      text: type === "keyDown" ? "\r" : undefined,
    });
  }
  await sleep(500);
  const quotedByKeyboard = await session.eval(
    `document.querySelector(".ProseMirror").innerHTML.includes("<blockquote")`);

  // --- the heading picker changes the block --------------------------------
  await session.click(".ProseMirror blockquote p, .ProseMirror p");
  await sleep(200);
  await session.click('[role="toolbar"] button[aria-haspopup="listbox"]');
  await sleep(400);
  await session.click('[role="listbox"] [role="option"]', (t) => t.trim() === "Heading 2");
  await sleep(500);
  const heading = await session.eval(`(() => {
    const pm = document.querySelector(".ProseMirror");
    const trigger = document.querySelector('[role="toolbar"] button[aria-haspopup="listbox"]');
    return {
      hasH2: !!pm.querySelector("h2"),
      // The picker must REPORT the block it is in, not just set it.
      triggerText: trigger ? trigger.textContent.trim() : null,
    };
  })()`);

  // Save and read the markdown back: the toolbar's job is the document.
  await session.eval(`(() => {
    [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Save")?.click();
  })()`);
  await sleep(2200);
  const saved = await session.eval(
    `(async () => (await (await fetch("/api/v1/pages/${created.id}", {credentials:"include"})).json()).body)()`);

  const hoverCapable = await session.eval(HOVER_CAPABLE_PROBE);

  const checks = {
    "the browser reports a hover-capable pointer": hoverCapable === true,
    "the editor renders our toolbar": chrome.ours === true && chrome.controlCount >= 10,
    "no editor renders Crepe's top bar": chrome.crepeTopBars === 0,
    "every control is keyboard reachable": chrome.unreachable.length === 0,
    "no control is clipped out of the bar": chrome.overflowing === 0,
    // The complaint, as an assertion: a press alone must do nothing.
    "pressing without releasing does not act": afterPressOnly === false,
    "releasing acts": afterRelease.bolded === true,
    "active state is announced": afterRelease.pressed === "true",
    "active state is VISIBLE, not just announced":
      afterRelease.background !== boldAt.background,
    "a control can be focused": viaKeyboard === true,
    "and run with Enter": quotedByKeyboard === true,
    "the heading picker sets the block": heading.hasH2 === true,
    "and reports the block it is in": heading.triggerText === "Heading 2",
    // The heading sits INSIDE the blockquote the keyboard test made, so the
    // line starts "> ## " — matching ^## would fail on correct output.
    "the document round-trips as markdown":
      /^>?\s*##\s/m.test(saved || "") && /\*\*/.test(saved || ""),
    "no console errors": consoleErrors.length === 0,
  };

  return report(checks, { hoverCapable, chrome, boldAt, afterPressOnly, afterRelease, viaKeyboard, quotedByKeyboard, heading, saved, consoleErrors });
}

main()
  .then((failed) => process.exit(failed ? 1 : 0))
  .catch((err) => { console.error(err); process.exit(2); });
