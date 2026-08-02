import { useState, type DragEvent as ReactDragEvent } from "react";

/**
 * Shared drop-TARGET wiring for bucket surfaces (spec 24): board columns
 * (ViewBoard), swimlane cells (ViewSwimlanes), and list sections (ViewList).
 * Owns the state every surface used to duplicate — the dragged payload and
 * which bucket is hovered — and builds the per-bucket dragover / dragleave /
 * drop handlers, including the two easy-to-get-wrong details:
 * - dragover only reacts to drags that STARTED here (`dragging` set), so
 *   foreign drags (files, text) are never accepted;
 * - dragleave ignores moves into a CHILD of the target (relatedTarget still
 *   contained), otherwise the highlight would flicker over every card.
 *
 * What a drop MEANS stays with the caller (the axis-dnd planners); ViewList's
 * within-section row REORDER wiring (rows capturing the drop with
 * stopPropagation) is a different gesture and stays local to ViewList.
 */

/** Spreadable handler trio for one bucket element ({} when drag is disabled). */
export interface BucketTargetProps {
  onDragOver?: (event: ReactDragEvent<HTMLElement>) => void;
  onDragLeave?: (event: ReactDragEvent<HTMLElement>) => void;
  onDrop?: (event: ReactDragEvent<HTMLElement>) => void;
}

export interface BucketDrop<TDrag> {
  /** The payload being dragged, or null — drives "surface is mid-drag" styles. */
  dragging: TDrag | null;
  /** True while `key`'s bucket is hovered by an eligible drag — highlight it. */
  isOver: (key: string) => boolean;
  /** Wire to the draggable child's onDragStart. */
  startDrag: (payload: TDrag) => void;
  /** Wire to the draggable child's onDragEnd; also clears any caller extras. */
  endDrag: () => void;
  /** Build the drop-target props for one bucket; `drop` gets the payload. */
  targetProps: (key: string, drop: (dragged: TDrag) => void) => BucketTargetProps;
}

export function useBucketDrop<TDrag>(
  enabled: boolean,
  /** Extra caller state to clear whenever a drag fully ends (drop OR dragend). */
  onClear?: () => void,
): BucketDrop<TDrag> {
  const [dragging, setDragging] = useState<TDrag | null>(null);
  const [overKey, setOverKey] = useState<string | null>(null);

  const endDrag = () => {
    setDragging(null);
    setOverKey(null);
    onClear?.();
  };

  const targetProps = (key: string, drop: (dragged: TDrag) => void): BucketTargetProps =>
    enabled
      ? {
          onDragOver: (event) => {
            if (!dragging) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setOverKey(key);
          },
          onDragLeave: (event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node)) return;
            setOverKey((k) => (k === key ? null : k));
          },
          onDrop: (event) => {
            event.preventDefault();
            if (dragging) drop(dragging);
            endDrag();
          },
        }
      : {};

  return {
    dragging,
    isOver: (key) => enabled && overKey === key,
    startDrag: setDragging,
    endDrag,
    targetProps,
  };
}
