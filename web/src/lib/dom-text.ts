/**
 * Mapping between an element's rendered text and DOM ranges (RADD-726).
 *
 * Inline comments anchor against the text a reader can SEE, not the markdown
 * source. Two reasons: the quote in a comment should be the words that were
 * selected, and the source contains formatting characters that a reader never
 * saw and would be baffled to find quoted back at them. It also means one
 * anchoring implementation covers prose, tables and code blocks alike.
 */

/** Every text node under `root`, in document order. */
export function textNodesOf(root: Node): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    nodes.push(node as Text);
  }
  return nodes;
}

/** The rendered text of `root` — the string offsets below index into. */
export function renderedText(root: Node): string {
  return textNodesOf(root)
    .map((node) => node.data)
    .join("");
}

/** A DOM Range covering [start, end) of `renderedText(root)`, or null. */
export function rangeForOffsets(root: Node, start: number, end: number): Range | null {
  let seen = 0;
  let startNode: Text | null = null;
  let startOffset = 0;
  let endNode: Text | null = null;
  let endOffset = 0;

  for (const node of textNodesOf(root)) {
    const next = seen + node.data.length;
    if (!startNode && start < next) {
      startNode = node;
      startOffset = start - seen;
    }
    if (startNode && end <= next) {
      endNode = node;
      endOffset = end - seen;
      break;
    }
    seen = next;
  }
  if (!startNode || !endNode) return null;
  const range = document.createRange();
  range.setStart(startNode, Math.max(0, startOffset));
  range.setEnd(endNode, Math.max(0, endOffset));
  return range;
}

/** Offsets into `renderedText(root)` for the current selection, or null when
 *  the selection is empty or lies outside `root`. */
export function offsetsForSelection(root: Node): { start: number; end: number } | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;

  let seen = 0;
  let start: number | null = null;
  let end: number | null = null;
  for (const node of textNodesOf(root)) {
    if (node === range.startContainer) start = seen + range.startOffset;
    if (node === range.endContainer) end = seen + range.endOffset;
    seen += node.data.length;
  }
  if (start === null || end === null || end <= start) return null;
  return { start, end };
}
