/** Unit cases for the hover-preview flattener (RADD-924).
 *
 * Tested here rather than through the browser on purpose. Proving it in CDP
 * meant hovering whatever the similar-issues ranker happened to return, and on a
 * 500k-item database that was an issue with no description at all — so the "no
 * raw markdown" assertion passed by describing nothing. The transform is pure;
 * test it purely, and let the CDP proof cover the wiring.
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "plaintext-"));
const file = join(dir, "plain-text.ts");
writeFileSync(file, readFileSync("web/src/lib/plain-text.ts", "utf8"));
const { toPlainText, previewText, PREVIEW_MAX_CHARS } = await import(file);

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

check("headings lose their markers", toPlainText("## What happened"), "What happened");

check(
  "a link keeps its text and loses its URL",
  toPlainText("See [the runbook](https://example.com/rb) first."),
  "See the runbook first.",
);

check("images go entirely", toPlainText("before ![a shot](https://x/y.png) after"), "before after");

check(
  "a fenced block is dropped rather than pasted in",
  toPlainText("Repro:\n\n```\nnpm run boom\n```\n\nThen it dies."),
  "Repro:\nThen it dies.",
);

check("inline code keeps its content", toPlainText("run `npm test` now"), "run npm test now");

check("emphasis markers go", toPlainText("**very** _bad_ ~~old~~"), "very bad old");

check("bullets become readable", toPlainText("- one\n- two"), "• one\n• two");

check("block quotes lose their marker", toPlainText("> quoted line"), "quoted line");

check(
  "a table collapses instead of arriving unaligned",
  toPlainText("text\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nmore"),
  "text\nmore",
);

check("blank runs collapse", toPlainText("a\n\n\n\nb"), "a\nb");

// The failure this exists to prevent: markdown syntax reaching a card whose
// entire job is being skimmable.
const messy = toPlainText("# Title\n\n```js\nboom()\n```\n\n![img](u) [text](url) **bold**");
check("nothing markdown-ish survives", /[#`]|!\[|\]\(/.test(messy), false);

check(
  "a long description is cut with an ellipsis",
  previewText("x".repeat(PREVIEW_MAX_CHARS + 50)).length,
  PREVIEW_MAX_CHARS + 1,
);

check("a short one is left alone", previewText("short enough"), "short enough");

check("empty in, empty out", toPlainText(""), "");

console.log(failures === 0 ? "\nall passed" : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
