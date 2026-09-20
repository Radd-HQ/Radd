/**
 * Protecting non-prose blocks through an AI run (RADD-1274).
 *
 * An editor AI run serialises the document to markdown, streams a replacement
 * and splices it back as a diff. A `radd:media` fence, an image, an attachment
 * link are lines of syntax the model has no reason to keep — asked to condense
 * a page it returns prose, the diff reads the player as a deletion, and
 * accepting the summary deleted the video (2026-09-20). Describing the syntax
 * in the prompt does not help: the model rewrites it, and a rewritten fence is
 * worse than a dropped one.
 *
 * So the model never sees them. Every protected fragment is replaced by an
 * opaque placeholder `⟦keep-N⟧` before the run and put back after it. The
 * system prompt carries one standing rule about placeholders (server side,
 * `prompts.EDITOR_SYSTEM`), and a placeholder the model dropped anyway is
 * appended to the end of the replacement — a block can move, it cannot vanish;
 * the diff then shows the move and the person decides.
 *
 * Pure functions over strings, no editor, so the test can name the exact
 * markdown in and out. The placeholder brackets are U+27E6/U+27E7, which no
 * page uses and no tokenizer splits into something that looks like prose.
 */

export interface KeptBlock {
  /** 1-based, stable for the run — a selection run shares ids with the document. */
  id: number;
  /** The original markdown, byte for byte. */
  text: string;
}

export interface MaskedMarkdown {
  masked: string;
  kept: KeptBlock[];
}

export const placeholderFor = (id: number): string => `⟦keep-${id}⟧`;

/** A placeholder as the model may hand it back: bare, or wrapped in backticks
 *  or bold markers it decided a "code-looking" token deserved. */
const PLACEHOLDER = /[`*_]*⟦keep-(\d+)⟧[`*_]*/g;

/** The prefix a line has to start with to open a protected fence. */
const FENCE_OPEN = /^( {0,3})(`{3,}|~{3,})[ \t]*radd:\S*/;

/** An inline image, or a link to one of our attachments (a file the page
 *  carries, which is not text the model can improve). */
const INLINE = /!\[[^\]\n]*\]\([^)\n]*\)|\[[^\]\n]*\]\([^)\n]*\/attachments\/[^)\n]*\)/g;

/**
 * Replace every protected fragment in `markdown` with a placeholder.
 *
 * `shared` is the document's own `kept` list when masking a SELECTION cut out
 * of that document: a fragment that also appears in the document reuses its
 * id, so the context the model reads and the part it rewrites agree on what
 * `⟦keep-3⟧` is. Ids for fragments outside the shared list continue after it.
 */
export function maskProtected(markdown: string, shared: KeptBlock[] = []): MaskedMarkdown {
  const kept: KeptBlock[] = [];
  const claimed = new Set<number>();
  let next = shared.reduce((max, block) => Math.max(max, block.id), 0) + 1;
  const keep = (text: string): string => {
    const reused = shared.find((block) => block.text === text && !claimed.has(block.id));
    const id = reused ? reused.id : next++;
    if (reused) claimed.add(id);
    kept.push({ id, text });
    return placeholderFor(id);
  };

  const lines = markdown.split("\n");
  const out: string[] = [];
  for (let i = 0; i < lines.length; i++) {
    const open = FENCE_OPEN.exec(lines[i]);
    if (open) {
      const fence = open[2];
      const block = [lines[i]];
      let j = i + 1;
      for (; j < lines.length; j++) {
        block.push(lines[j]);
        const close = /^ {0,3}(`{3,}|~{3,})[ \t]*$/.exec(lines[j]);
        if (close && close[1][0] === fence[0] && close[1].length >= fence.length) break;
      }
      out.push(keep(block.join("\n")));
      i = j;
      continue;
    }
    out.push(lines[i].replace(INLINE, (match) => keep(match)));
  }
  return { masked: out.join("\n"), kept };
}

/**
 * Put the originals back. Every placeholder the model kept is replaced in
 * place; one it invented (an id we never issued) is removed; the ones it
 * dropped are appended, in their original order, each as its own paragraph.
 */
export function restoreProtected(text: string, kept: KeptBlock[]): string {
  const byId = new Map(kept.map((block) => [block.id, block.text]));
  const seen = new Set<number>();
  const restored = text.replace(PLACEHOLDER, (_match, digits: string) => {
    const id = Number(digits);
    const original = byId.get(id);
    if (original === undefined) return "";
    seen.add(id);
    return original;
  });
  const dropped = kept.filter((block) => !seen.has(block.id));
  if (dropped.length === 0) return restored;
  const tail = dropped.map((block) => block.text).join("\n\n");
  return restored.trimEnd() === "" ? tail : `${restored.trimEnd()}\n\n${tail}\n`;
}

/** How many protected fragments a replacement lost — for the panel's copy. */
export function droppedCount(text: string, kept: KeptBlock[]): number {
  const seen = new Set<number>();
  for (const match of text.matchAll(PLACEHOLDER)) seen.add(Number(match[1]));
  return kept.filter((block) => !seen.has(block.id)).length;
}
