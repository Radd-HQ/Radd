import { useQuery } from "@tanstack/react-query";
import { DEFLECT_DEBOUNCE_MS, DEFLECT_MIN_QUERY_CHARS } from "../../lib/constants";
import { deflectQuery } from "../../lib/queries";
import { DeflectPagesSection, DeflectItemsSection } from "../items/DeflectionPanel";
import { Slot, SlotId, useDebounced } from "@radd/plugin-sdk";

interface FormAssistPanelProps {
  /** The draft title — seeds deflection alone (FTS wants short, dense text). */
  title: string;
  /** The draft description — contributions may read the whole draft. */
  description: string;
  projectId: string;
  className?: string;
}

/**
 * Submit-time assist for the AUTHED form pages (spec 106): KB deflection (spec 66) — pages that
 * may already answer it and previously RESOLVED issues — plus whatever plugins suggest beside a
 * draft through `item.draft.assist` (RADD-1395; the ai plugin's "Similar issues" surfaces the OPEN
 * duplicates deflection deliberately hides). Renders nothing until the title is long enough, and
 * the frame hides itself while every section is empty (`empty:hidden`: a contribution with nothing
 * to say renders nothing). Every link opens a new tab or the peek, so the half-typed form survives.
 * Mounted twice per page (inline on narrow, an aside when the container is wide) — the queries
 * dedupe on their keys, so the second mount is free.
 */
export function FormAssistPanel({ title, description, projectId, className = "" }: FormAssistPanelProps) {
  const debouncedTitle = useDebounced(title, DEFLECT_DEBOUNCE_MS);
  const deflect = useQuery(deflectQuery(debouncedTitle, projectId));
  const docs = deflect.data?.docs ?? [];
  const resolved = deflect.data?.items ?? [];

  // Gate on the LIVE title too — kept-previous data must not outlive a cleared draft.
  if (title.trim().length < DEFLECT_MIN_QUERY_CHARS) return null;

  return (
    <div className={"flex flex-col gap-2.5 rounded-md border border-subtle bg-surface/40 p-2.5 empty:hidden " + className}>
      <DeflectPagesSection docs={docs} />
      <DeflectItemsSection items={resolved} />
      {/* Deflection already shows the resolved twins — contributions do not repeat them. */}
      <Slot
        id={SlotId.itemDraftAssist}
        title={title}
        description={description}
        projectId={projectId}
        exclude={resolved.map((item) => item.key)}
      />
    </div>
  );
}
