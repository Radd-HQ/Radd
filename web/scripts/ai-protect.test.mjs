/**
 * Unit cases for protecting non-prose blocks through an AI run (RADD-1274).
 *
 * The cases that matter: a `radd:media` fence and an image leave the model's
 * input as placeholders and come back byte for byte; a placeholder the model
 * dropped is appended rather than lost; a selection cut from a document shares
 * the document's ids; and prose is untouched.
 *
 * Run: node --experimental-strip-types web/scripts/ai-protect.test.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "ai-protect-"));
const file = join(dir, "ai-protect.ts");
writeFileSync(file, readFileSync("web/src/components/editor/ai-protect.ts", "utf8"));
const { maskProtected, restoreProtected, droppedCount, placeholderFor } = await import(file);

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

const MEDIA = '```radd:media\n{"src": "/api/v1/attachments/abc", "kind": "video", "title": "Standup.mp4"}\n```';
const IMAGE = "![whiteboard](/api/v1/attachments/def?w=640)";
const FILE = "[spec.pdf](/api/v1/attachments/ghi)";
const doc = `# Meeting\n\nFirst paragraph.\n\n${MEDIA}\n\nSecond paragraph with ${IMAGE} inline and ${FILE}.\n\nThird.\n`;

// --- masking
const { masked, kept } = maskProtected(doc);
check("three fragments are kept", kept.map((k) => k.text), [MEDIA, IMAGE, FILE]);
check("the fence became a placeholder line", masked.includes(`\n\n${placeholderFor(1)}\n\n`), true);
check("the image is an inline placeholder", masked.includes(`with ${placeholderFor(2)} inline`), true);
check("the attachment link is an inline placeholder", masked.includes(`and ${placeholderFor(3)}.`), true);
check("no raw syntax reaches the model", /radd:media|!\[|attachments\//.test(masked), false);
check("prose is untouched", masked.startsWith("# Meeting\n\nFirst paragraph.\n\n"), true);

// --- restoring
check("identity: restore(mask(doc)) is doc", restoreProtected(masked, kept), doc);
const summary = `## Summary\n\n- The meeting.\n\n${placeholderFor(1)}\n\n- One image: \`${placeholderFor(2)}\`\n`;
const restored = restoreProtected(summary, kept);
check("kept placeholders come back in place, even wrapped in backticks", restored.includes(`- One image: ${IMAGE}`), true);
check("the fence comes back whole", restored.includes(MEDIA), true);
check("the dropped attachment link is appended, not lost", restored.trimEnd().endsWith(FILE), true);
check("droppedCount counts the one the model lost", droppedCount(summary, kept), 1);
check("a placeholder we never issued is removed", restoreProtected("x ⟦keep-9⟧ y", kept.slice(0, 0)), "x  y");
check("an empty reply becomes the protected blocks alone", restoreProtected("", kept), `${MEDIA}\n\n${IMAGE}\n\n${FILE}`);

// --- a selection shares the document's ids
const selection = `Second paragraph with ${IMAGE} inline and ${FILE}.`;
const sel = maskProtected(selection, kept);
check("selection fragments reuse the document's ids", sel.kept.map((k) => k.id), [2, 3]);
check("a fragment only in the selection gets a fresh id after the document's", maskProtected(`${IMAGE} and ![new](/x.png)`, kept).kept.map((k) => k.id), [2, 4]);

// --- fences: tilde fences, longer closers, unterminated
const tilde = "~~~~radd:toc\n{}\n~~~~\nafter";
check("a tilde fence is a block", maskProtected(tilde).kept[0].text, "~~~~radd:toc\n{}\n~~~~");
check("an unterminated fence runs to the end", maskProtected("```radd:mermaid\ngraph TD").kept[0].text, "```radd:mermaid\ngraph TD");
check("an ordinary code fence is prose to the model", maskProtected("```python\nprint(1)\n```").kept.length, 0);

if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all ai-protect cases pass");
