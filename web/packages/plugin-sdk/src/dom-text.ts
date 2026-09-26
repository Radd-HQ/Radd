/**
 * Mapping between an element's rendered text and DOM ranges (RADD-726).
 *
 * Inline comments anchor against the text a reader can SEE, not the markdown
 * source. Two reasons: the quote in a comment should be the words that were
 * selected, and the source contains formatting characters that a reader never
 * saw and would be baffled to find quoted back at them. It also means one
 * anchoring implementation covers prose, tables and code blocks alike.
 */

type DomPoint = { node: Node; offset: number };
interface TextProjection {
  pointAt: (offset: number) => DomPoint | null;
  offsetAt: (node: Node, offset: number) => number | null;
  reveal: (offset: number) => void;
}
// CodeMirror virtualizes visible lines. Its ProseMirror source supplies stable
// text; the editor supplies the corresponding visible DOM points on demand.
const projections = new WeakMap<Element, TextProjection>();
export function registerTextProjection(source: Element, projection: TextProjection): () => void {
  projections.set(source, projection);
  return () => { projections.delete(source); };
}

/** Every document text node, excluding duplicate code DOM and editor chrome. */
export function textNodesOf(root: Node): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const parent = node.parentElement;
    if (parent?.closest("[data-code-block]") && !parent.closest("[data-code-source]")) continue;
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
function sourceRangeForOffsets(root: Node, start: number, end: number): Range | null {
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

function sourceOffset(source: Element, node: Node, offset: number): number {
  const before = document.createRange();
  before.selectNodeContents(source);
  before.setEnd(node, offset);
  return before.toString().length;
}

function visiblePoint(node: Node, offset: number): DomPoint | null {
  const source = node.parentElement?.closest("[data-code-source]");
  if (!source) return {node, offset};
  return projections.get(source)?.pointAt(sourceOffset(source, node, offset)) ?? null;
}

/** Visible range, or null when the code editor has not rendered that line yet. */
export function rangeForOffsets(root: Node, start: number, end: number): Range | null {
  const source = sourceRangeForOffsets(root, start, end);
  if (!source) return null;
  const from = visiblePoint(source.startContainer, source.startOffset);
  const to = visiblePoint(source.endContainer, source.endOffset);
  if (!from || !to) return null;
  const range = document.createRange();
  range.setStart(from.node, from.offset);
  range.setEnd(to.node, to.offset);
  return range;
}

/** Materialize a virtualized code line before measuring its DOM range. */
export async function revealTextOffset(root: Node, offset: number): Promise<void> {
  const range = sourceRangeForOffsets(root, offset, offset + 1);
  const source = range?.startContainer.parentElement?.closest("[data-code-source]");
  if (!source || !range) return;
  projections.get(source)?.reveal(sourceOffset(source, range.startContainer, range.startOffset));
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
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
  const projectedOffset = (node: Node, offset: number) => {
    const block = node.parentElement?.closest("[data-code-block]");
    const source = block?.querySelector("[data-code-source]");
    const local = source ? projections.get(source)?.offsetAt(node, offset) : null;
    return source && local != null ? {source, offset: local} : null;
  };
  const projectedStart = projectedOffset(range.startContainer, range.startOffset);
  const projectedEnd = projectedOffset(range.endContainer, range.endOffset);
  const seenSources = new Set<Element>();
  for (const node of textNodesOf(root)) {
    const source = node.parentElement?.closest("[data-code-source]");
    if (source && !seenSources.has(source)) {
      if (source === projectedStart?.source) start = seen + projectedStart.offset;
      if (source === projectedEnd?.source) end = seen + projectedEnd.offset;
      seenSources.add(source);
    }
    if (node === range.startContainer) start = seen + range.startOffset;
    if (node === range.endContainer) end = seen + range.endOffset;
    seen += node.data.length;
  }
  if (start === null || end === null || end <= start) return null;
  return { start, end };
}

/** Center the actual passage, including text deep inside a large code block.
 * Scroll its own ancestors only; never move the independent comment sidebar. */
export function scrollRangeIntoView(range: Range): void {
  let element = range.startContainer.parentElement;
  while (element) {
    if (element.scrollHeight > element.clientHeight && /(auto|scroll)/.test(getComputedStyle(element).overflowY)) {
      const passage = range.getBoundingClientRect();
      const viewport = element.getBoundingClientRect();
      element.scrollTop += passage.top - viewport.top - element.clientTop
        - (element.clientHeight - Math.min(passage.height, element.clientHeight)) / 2;
    }
    element = element.parentElement;
  }
  if (document.scrollingElement && document.scrollingElement.scrollHeight > window.innerHeight) {
    const passage = range.getBoundingClientRect();
    window.scrollBy({top: passage.top - (window.innerHeight - Math.min(passage.height, window.innerHeight)) / 2, behavior: "instant"});
  }
}
