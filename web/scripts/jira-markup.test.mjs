/** Unit cases for the Jira backwards-compat transform (RADD-1006).
 *
 * The bug this guards against is INVISIBLE at every layer that could have
 * caught it: the API round-trips the body unchanged, the page renders, no
 * console error appears, and only the document's heading structure is gone. A
 * browser proof would not have found it either — the headings were replaced by
 * a plausible-looking code block, so the page still had content.
 *
 * The transform is pure, so test it purely.
 *
 * Run from the repo root: node web/scripts/jira-markup.test.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "jiramarkup-"));
const file = join(dir, "jira-markup.ts");
writeFileSync(file, readFileSync("web/src/lib/jira-markup.ts", "utf8"));
const { jiraToMarkdown } = await import(file);

let failures = 0;
const check = (label, actual, expected) => {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    console.log(`FAIL ${label}\n  got      ${a}\n  expected ${e}`);
    failures++;
  } else {
    console.log(`ok   ${label}`);
  }
};

// --- RADD-1006: `{{` must not make a markdown body "Jira" -------------------
//
// Each of these is a native markdown body that happens to contain two braces.
// The transform must return it UNTOUCHED. Before the fix every one of them came
// back with `## Heading` rewritten to `····1. Heading`, which markdown renders
// as an indented code block.

const templateToken = "## Heading\n\nUse {{issue.key}} in the reply.\n";
check("a canned-response token leaves the body alone", jiraToMarkdown(templateToken), templateToken);

const automationToken = "## Actions\n\nThe action can use {{item.title}}.\n";
check("an automation token leaves the body alone", jiraToMarkdown(automationToken), automationToken);

const jsxSample = '## The model\n\nText.\n\n```tsx\n<div style={{ display: "flex" }}>\n```\n\n## Next\n';
check("a JSX sample in a fence leaves the body alone", jiraToMarkdown(jsxSample), jsxSample);

const bracesOnly = "## First\n\n```\n{{ display: 1 }}\n```\n\n## Second\n";
check("bare double braces leave the body alone", jiraToMarkdown(bracesOnly), bracesOnly);

// The specific corruption, stated as its own case so a regression names itself.
check(
  "a markdown heading never becomes an indented list item",
  jiraToMarkdown("## The model\n\n{{x}}\n").includes("    1. The model"),
  false,
);

// --- Genuine Jira bodies must still convert ---------------------------------
//
// Removing `{{` from the gate must not stop real Jira text from being handled.
// A real Jira body always carries at least one unambiguous signal.

check(
  "a Jira heading still converts",
  jiraToMarkdown("h2. Overview\n\nText.\n").startsWith("## Overview"),
  true,
);
check(
  "Jira monospace still converts when the body is really Jira",
  jiraToMarkdown("h2. T\n\nRun {{npm test}} first.\n").includes("`npm test`"),
  true,
);
check(
  "a Jira ordered list still converts",
  jiraToMarkdown("h1. T\n\n# one\n## two\n").includes("1. one"),
  true,
);
check(
  "a {code} block still converts",
  jiraToMarkdown("{code:js}\nconst a = 1;\n{code}\n").includes("```js"),
  true,
);
check("plain markdown is returned untouched", jiraToMarkdown("# Title\n\nBody.\n"), "# Title\n\nBody.\n");
check("empty input is safe", jiraToMarkdown(""), "");

console.log(failures ? `\n${failures} failure(s)` : "\nall cases passed");
process.exit(failures ? 1 : 0);
