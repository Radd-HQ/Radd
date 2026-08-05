/**
 * Proves RADD-875: the issue rail's state + priority chips render the TOKEN
 * scales (--chart-*, --priority-*), not the drifted hex maps this file used to
 * shadow them with — in BOTH themes, with the non-inverting dark glyph.
 *
 * Method: resolve the expected var() through a probe element, then compare the
 * chip's computed background against it — measuring, not eyeballing.
 *
 * Usage: node scripts/state-chip-proof.mjs <baseUrl> <issueKey> <email> <password>
 */
import { resolve } from "node:path";
import { openBrowser, report } from "./lib/cdp.mjs";

const [baseUrl, issueKey, email, password] = process.argv.slice(2);
const PORT = 9461;
const PROFILE = resolve(process.env.TMPDIR || "/tmp", "radd-state-chip-proof");

/** Chip facts for the current theme. */
const PROBE = `(() => {
  const resolveVar = (name) => {
    const el = document.createElement("span");
    el.style.backgroundColor = "var(" + name + ")";
    document.body.appendChild(el);
    const color = getComputedStyle(el).backgroundColor;
    el.remove();
    return color;
  };
  const chips = [...document.querySelectorAll("span[title][aria-label]")].map((chip) => ({
    label: chip.getAttribute("aria-label"),
    bg: getComputedStyle(chip).backgroundColor,
    glyph: getComputedStyle(chip).color,
  }));
  return { chips, resolveVar: {
    progress: resolveVar("--chart-progress"),
    todo: resolveVar("--chart-todo"),
    triage: resolveVar("--chart-triage"),
    backlog: resolveVar("--chart-backlog"),
    done: resolveVar("--chart-done"),
    canceled: resolveVar("--chart-canceled"),
    blocker: resolveVar("--priority-blocker"),
    high: resolveVar("--priority-high"),
    normal: resolveVar("--priority-normal"),
    low: resolveVar("--priority-low"),
  } };
})()`;

async function main() {
  const { session } = await openBrowser({ port: PORT, profile: PROFILE, width: 1440, height: 1000 });

  await session.navigate(baseUrl + "/", 1200);
  await session.login(baseUrl, email, password);

  const item = await session.eval(`(async () => {
    const res = await fetch("/api/v1/items/by-key/" + ${JSON.stringify(issueKey)}, { credentials: "include" });
    const it = await res.json();
    return { category: it.state.category, stateName: it.state.name, priority: it.priority };
  })()`);

  await session.navigate(baseUrl + "/issues/" + issueKey, 2500);

  const catKey = item.category === "in_progress" ? "progress" : item.category;
  const themes = {};
  for (const theme of ["dark", "light"]) {
    await session.eval(
      `document.documentElement.classList.toggle("light", ${JSON.stringify(theme)} === "light"); "ok"`,
    );
    const probe = await session.eval(PROBE);
    const state = probe.chips.find((c) => c.label === item.stateName);
    const prio = probe.chips.find(
      (c) => c.label.toLowerCase() === item.priority || c.label.toLowerCase() === item.priority + " priority",
    ) ?? probe.chips.find((c) => ["Blocker", "High", "Normal", "Low"].includes(c.label));
    themes[theme] = {
      stateChipMatchesToken: !!state && state.bg === probe.resolveVar[catKey],
      priorityChipMatchesToken: !!prio && prio.bg === probe.resolveVar[item.priority],
      darkGlyph: !!state && state.glyph === "rgb(24, 24, 27)",
      state,
      chipsSeen: probe.chips,
      expected: probe.resolveVar[catKey],
    };
  }

  report(
    {
      "state chip = --chart token (dark)": themes.dark.stateChipMatchesToken,
      "state chip = --chart token (light)": themes.light.stateChipMatchesToken,
      "chip follows the theme (fills differ)": themes.dark.expected !== themes.light.expected,
      "priority chip = --priority token (dark)": themes.dark.priorityChipMatchesToken,
      "priority chip = --priority token (light)": themes.light.priorityChipMatchesToken,
      "non-inverting dark glyph in both themes": themes.dark.darkGlyph && themes.light.darkGlyph,
      "no console errors": session.consoleErrors.length === 0,
    },
    { item, dark: themes.dark, light: themes.light, consoleErrors: session.consoleErrors },
  );
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
