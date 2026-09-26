import { useState, type DragEvent as ReactDragEvent } from "react";

/**
 * Drop-TARGET wiring for bucket surfaces (board columns, swimlane cells, list sections): the
 * dragged payload, the hovered bucket, and per-bucket handlers that get two details right —
 * dragover accepts only drags that STARTED here (never files/text), and dragleave ignores moves
 * into a CHILD (or the highlight flickers over every card). What a drop MEANS is the caller's.
 */

/** Spreadable handler trio for one bucket element ({} when drag is disabled). */
interface BucketTargetProps {
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
