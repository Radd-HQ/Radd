/**
 * Markdown flattened to prose (RADD-924).
 *
 * A description is markdown, and a preview whose whole job is being skimmable
 * must not show `##`, fenced code, or `](https://…)`. This is deliberately a
 * FLATTENER, not a renderer: fences and images go, link URLs go and their TEXT
 * stays (it is usually the meaningful noun), and blank runs collapse.
 *
 * Its own module so it can be unit-tested directly. Proving it through the
 * browser meant hovering whatever the similar-issues ranker happened to return,
 * and on a 500k-item database that was an issue with no description at all —
 * which made the "no raw markdown" assertion pass by describing nothing.
 */

/** Longest prefix to keep; callers append an ellipsis when they cut. */
export const PREVIEW_MAX_CHARS = 420;

export function toPlainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ") // fenced code — never informative in a preview
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ") // images
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // links → their text
    .replace(/^\s{0,3}#{1,6}\s+/gm, "") // heading markers
    .replace(/^\s{0,3}>\s?/gm, "") // block quotes
    .replace(/^\s*[-*+]\s+/gm, "• ")
    .replace(/^\s*\|.*\|\s*$/gm, " ") // table rows — unreadable unaligned
    .replace(/[*_~]{1,3}/g, "")
    // Line-wise last, and not a `\n{2,}` collapse: the steps above replace whole
    // blocks with a SPACE, which leaves whitespace-only lines that a newline-run
    // pattern cannot see. A fence between two paragraphs came out as "a\n \nb".
    .split("\n")
    .map((line) => line.replace(/[ \t]{2,}/g, " ").trim())
    .filter((line) => line.length > 0)
    .join("\n");
}

/** The flattened text, cut to `PREVIEW_MAX_CHARS` with an ellipsis when it ran long. */
export function previewText(markdown: string): string {
  const plain = toPlainText(markdown);
  return plain.length > PREVIEW_MAX_CHARS
    ? `${plain.slice(0, PREVIEW_MAX_CHARS)}…`
    : plain;
}
