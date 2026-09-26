/** A line-level LCS diff of two stored page versions (RADD-720). Not the editor's diff plugin: that is
 *  an accept/reject decoration inside an editable document; this is a read-only question about two
 *  strings, at the granularity people read a wiki diff. */

type DiffOp = "same" | "add" | "remove";

interface DiffLine {
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

/** Collapse unchanged runs to `context` lines either side of a change. */
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
