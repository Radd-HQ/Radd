/**
 * Protecting non-prose blocks through an AI run (RADD-1274). A run sends markdown and splices the
 * reply back as a diff, so a `radd:*` fence, image or attachment link the model does not return
 * reads as a deletion — and describing the syntax in the prompt only gets it rewritten. So the
 * model never sees them: each becomes `⟦keep-N⟧` and is restored after, and one the model dropped
 * is appended (a block can move, never vanish). `prompts.EDITOR_SYSTEM` carries the one
 * placeholder rule. U+27E6/U+27E7 because no page uses them and no tokenizer splits them into
 * prose. Pure string functions, so the test names exact markdown in and out.
 */

interface KeptBlock {
  /** 1-based, stable for the run — a selection run shares ids with the document. */
  id: number;
  /** The original markdown, byte for byte. */
  text: string;
}

interface MaskedMarkdown {
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
