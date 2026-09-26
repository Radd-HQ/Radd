/** Page-eval probes for the automation editor, shared by the automation proofs. */
import { sleep } from "./cdp.mjs";

/** Press the list row's Edit button for the automation called `name`. (Its first button is the
 *  Enabled switch, so "click the row's first button" would switch the rule on instead.) */
export const openRule = (name) => `(() => {
  const button = document.querySelector(${JSON.stringify(`[aria-label="Edit ${name}"]`)});
  if (button) button.click();
  return Boolean(button);
})()`;

/** Land on Settings → Automations, open `name`, and wait for the lazy canvas. Returns whether the
 *  row was found. */
export async function openEditor(session, baseUrl, name) {
  await session.navigate(`${baseUrl}/settings/automations`, 2200);
  const opened = await session.eval(openRule(name));
  await sleep(2500);
  return opened;
}

/** Type `text` into the node panel's search box. */
export const searchNodes = (text) => `(() => {
  const input = document.querySelector('[data-node-panel] input[aria-label="Search nodes"]');
  if (!input) return false;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(text)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return true;
})()`;

/** Click the first node-panel row whose text matches `pattern` (a RegExp). */
export const clickPanelRow = (pattern) => `(() => {
  const row = [...document.querySelectorAll("[data-node-panel] li button")].find((b) => ${pattern}.test(b.textContent || ""));
  if (row) row.click();
  return Boolean(row);
})()`;

/** The node panel's row labels. */
export const PANEL_ROWS = `[...document.querySelectorAll("[data-node-panel] li button")].map((b) => b.textContent.trim())`;

/** Press the editor's submit (Save changes, or Create automation). */
export const SAVE = `(() => {
  const button = [...document.querySelectorAll("button[type=submit]")]
    .find((b) => /save changes|create automation/i.test(b.textContent || ""));
  if (!button) return false;
  button.click();
  return true;
})()`;

/** What the editor said about the last save. */
export const SAVE_STATE = `(() => {
  const text = document.body.innerText;
  const match = text.match(/Rejected on save:[^\\n]*/);
  return { rejected: match ? match[0] : null, saved: /\\bSaved\\b/.test(text) };
})()`;
