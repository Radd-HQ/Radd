/**
 * Proves RADD-881: the kit Select grows a real filter above SEARCHABLE_THRESHOLD
 * options — measured against the worst real surface, the issue rail's Assignee
 * picker over the full user directory (~3k options on the perf-seed DB).
 *
 *  - the panel opens with a filter input (combobox), not just jump type-ahead;
 *  - rendered rows are CAPPED with a "keep typing — N more" tail;
 *  - typing narrows to the real match;
 *  - a small select (<= threshold) keeps the classic panel, no filter input.
 *
 * Usage: node scripts/select-search-proof.mjs <baseUrl> <issueKey> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report, sleep } from "./lib/cdp.mjs";

const [baseUrl, issueKey, email, password] = process.argv.slice(2);
const PORT = 9462;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-select-search-proof");

const OPEN_BY_LABEL = (labelText) => `(() => {
  const label = [...document.querySelectorAll("label")].find(
    (l) => l.textContent.trim() === ${JSON.stringify(labelText)},
  );
  if (!label) return { ok: false, reason: "no label" };
  const trigger = document.getElementById(label.htmlFor);
  if (!trigger) return { ok: false, reason: "no trigger" };
  trigger.click();
  return { ok: true };
})()`;

const PANEL_PROBE = `(() => {
  const list = document.querySelector('ul[role="listbox"]');
  if (!list) return { open: false };
  const input = list.parentElement.querySelector('input[role="combobox"]');
  const rows = [...list.querySelectorAll('li[role="option"]')];
  const tail = [...list.querySelectorAll("li")].find((li) =>
    (li.textContent || "").startsWith("Keep typing"),
  );
  return {
    open: true,
    hasFilterInput: !!input,
    rowCount: rows.length,
    tailText: tail ? tail.textContent : null,
    rowLabels: rows.slice(0, 5).map((r) => r.textContent.trim()),
  };
})()`;

const TYPE_IN_FILTER = (text) => `(() => {
  const input = document.querySelector('ul[role="listbox"]')
    ?.parentElement.querySelector('input[role="combobox"]');
  if (!input) return { ok: false };
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  setter.call(input, ${JSON.stringify(text)});
  input.dispatchEvent(new Event("input", { bubbles: true }));
  return { ok: true };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);
  await session.navigate(baseUrl + "/issues/" + issueKey, 2500);

  // Big select: the Assignee picker over the whole directory.
  const opened = await session.eval(OPEN_BY_LABEL("Assignee"));
  await sleep(300);
  const before = await session.eval(PANEL_PROBE);

  await session.eval(TYPE_IN_FILTER("hussein"));
  await sleep(300);
  const after = await session.eval(PANEL_PROBE);

  // Close the panel (Escape) and open a SMALL select: State (a handful of rows).
  await session.eval(`document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); "ok"`);
  await sleep(200);
  const openedSmall = await session.eval(OPEN_BY_LABEL("State"));
  await sleep(300);
  const small = await session.eval(PANEL_PROBE);

  report(
    {
      "assignee panel opens": opened.ok && before.open,
      "big select carries a filter input": before.hasFilterInput === true,
      "rows are capped at 200": before.rowCount <= 200 && before.rowCount >= 150,
      "the cap announces the remainder": !!before.tailText && /more match/.test(before.tailText),
      "typing narrows to the real match": after.open &&
        after.rowCount < before.rowCount &&
        after.rowLabels.some((l) => l.toLowerCase().includes("hussein")),
      "small select keeps the classic panel": small.open && small.hasFilterInput === false,
      "no console errors": session.consoleErrors.length === 0,
    },
    { before, after, small, consoleErrors: session.consoleErrors },
  );
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
