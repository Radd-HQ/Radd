/**
 * A line-level unified diff (RADD-720).
 *
 * Deliberately not the editor's diff machinery. That is a ProseMirror decoration
 * plugin built for accept/reject INSIDE an editable document (spec 103) — using
 * it to compare two stored versions would mean instantiating an editor per
 * comparison, feeding it a document nobody may edit, and suppressing the accept
 * and reject controls that are its entire purpose. Comparing versions is a
 * read-only question about two strings.
 *
 * Classic LCS over lines. A page is prose; line granularity is what people read
 * a wiki diff at, and word-level noise inside a rewritten paragraph obscures
 * more than it shows.
 */

export type DiffOp = "same" | "add" | "remove";

export interface DiffLine {
  op: DiffOp;
  text: string;
  /** 1-based line number in the old text (null for an addition). */
  oldLine: number | null;
  /** 1-based line number in the new text (null for a removal). */
  newLine: number | null;
}

/** Longest-common-subsequence table over two line arrays. */
function lcsTable(a: string[], b: string[]): number[][] {
  const table: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      table[i][j] =
        a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  return table;
}

export function diffLines(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  const table = lcsTable(a, b);
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ op: "same", text: a[i], oldLine: i + 1, newLine: j + 1 });
      i++;
      j++;
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      out.push({ op: "remove", text: a[i], oldLine: i + 1, newLine: null });
      i++;
    } else {
      out.push({ op: "add", text: b[j], oldLine: null, newLine: j + 1 });
      j++;
    }
  }
  while (i < a.length) out.push({ op: "remove", text: a[i], oldLine: ++i, newLine: null });
  while (j < b.length) out.push({ op: "add", text: b[j], oldLine: null, newLine: ++j });
  return out;
}

/**
 * Collapse long unchanged stretches, keeping `context` lines either side of a
 * change. A 400-line page with a one-word fix should not render 400 lines —
 * finding the change is the entire point of opening a diff.
 */
export function collapseUnchanged(
  lines: DiffLine[],
  context = 3,
): (DiffLine | { op: "skip"; count: number })[] {
  const keep = new Set<number>();
  lines.forEach((line, index) => {
    if (line.op === "same") return;
    for (let k = index - context; k <= index + context; k++) {
      if (k >= 0 && k < lines.length) keep.add(k);
    }
  });
  const out: (DiffLine | { op: "skip"; count: number })[] = [];
  let skipped = 0;
  lines.forEach((line, index) => {
    if (keep.has(index)) {
      if (skipped) {
        out.push({ op: "skip", count: skipped });
        skipped = 0;
      }
      out.push(line);
    } else {
      skipped++;
    }
  });
  if (skipped) out.push({ op: "skip", count: skipped });
  return out;
}

/** Counts for the summary line — what a reader wants before reading. */
export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  return {
    added: lines.filter((line) => line.op === "add").length,
    removed: lines.filter((line) => line.op === "remove").length,
  };
}
