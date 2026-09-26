import { useQuery } from "@tanstack/react-query";
import { BookOpen, CheckCircle2 } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { DEFLECT_DEBOUNCE_MS, DEFLECT_MIN_QUERY_CHARS, RoutePath } from "../../lib/constants";
import { useOpenIssueRef } from "../../lib/hooks";
import { deflectQuery } from "../../lib/queries";
import type { DeflectPage, DeflectItem } from "../../lib/types";
import { SimilarHoverCard, useIssuePreview } from "./SimilarHoverCard";
import { pagePermalink } from "@radd-plugin-ui/pages/links";
import { useDebounced } from "@radd/plugin-sdk";

interface DeflectionPanelProps {
  /** The half-typed issue title driving the lookup. */
  query: string;
  projectId: string;
}

/** KB deflection for a draft title (spec 66), debounced. `ready` gates on the LIVE text too, so
 *  kept-previous data never outlives a cleared draft. */
export function useDeflection(text: string, projectId: string) {
  const debounced = useDebounced(text, DEFLECT_DEBOUNCE_MS);
  const deflect = useQuery(deflectQuery(debounced, projectId));
  return {
    docs: deflect.data?.docs ?? [],
    items: deflect.data?.items ?? [],
    ready: text.trim().length >= DEFLECT_MIN_QUERY_CHARS,
  };
}

/**
 * KB deflection while the reporter types a title: pages that may already answer it and previously
 * RESOLVED issues, so they can stop filing. Renders nothing until something matches. Issue rows
 * open in the PEEK (the half-typed form survives); page rows open in a new tab. Not on the PUBLIC
 * form page (the endpoint is authenticated).
 */
export function DeflectionPanel({ query, projectId }: DeflectionPanelProps) {
  const { docs, items, ready } = useDeflection(query, projectId);
  if (!ready || (docs.length === 0 && items.length === 0)) return null;

  return (
    <div className="flex flex-col gap-2.5 rounded-md border border-subtle bg-surface/40 p-2.5">
      <DeflectPagesSection docs={docs} />
      <DeflectItemsSection items={items} />
    </div>
  );
}

/** Pages that may already answer the draft. */
export function DeflectPagesSection({ docs }: { docs: DeflectPage[] }) {
  if (docs.length === 0) return null;
  return (
    <section className="flex flex-col gap-1">
      <h3 className="flex items-center gap-1.5 text-[11px] font-medium text-fg-secondary">
        <BookOpen size={12} aria-hidden />
        Maybe this answers it
      </h3>
      <ul className="flex flex-col gap-0.5">
        {docs.map((doc) => (
          <li key={doc.id}>
            <Link
              {...pagePermalink(doc.id)}
              target="_blank"
              rel="noreferrer"
              className="group flex items-baseline gap-1.5 text-xs text-fg hover:text-accent-text"
            >
              <span className="truncate underline-offset-2 group-hover:underline">
                {doc.title}
              </span>
              <span className="shrink-0 text-[10px] text-fg-faint">{doc.space_name}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Previously RESOLVED issues matching the draft — plain clicks peek
 * (peek-aware via useOpenIssueRef; modified clicks keep the real href). */
export function DeflectItemsSection({ items }: { items: DeflectItem[] }) {
  const openRef = useOpenIssueRef();
  if (items.length === 0) return null;
  return (
    <section className="flex flex-col gap-1">
      <h3 className="flex items-center gap-1.5 text-[11px] font-medium text-fg-secondary">
        <CheckCircle2 size={12} aria-hidden />
        Previously resolved
      </h3>
      <ul className="flex flex-col gap-0.5">
        {items.map((item) => (
          <DeflectItemRow key={item.key} item={item} openRef={openRef} />
        ))}
      </ul>
    </section>
  );
}


/** One suggested duplicate, with the shared hover preview. */
function DeflectItemRow({
  item,
  openRef,
}: {
  item: DeflectItem;
  openRef: ReturnType<typeof useOpenIssueRef>;
}) {
  const preview = useIssuePreview();
  return (
    <li {...preview.handlers}>
      {preview.anchor && <SimilarHoverCard itemKey={item.key} anchor={preview.anchor} />}
      <Link
        to={RoutePath.issue}
        params={{ itemKey: item.key }}
        onClick={(event) => void openRef(item.key, event)}
        className="group flex items-baseline gap-1.5 text-xs text-fg hover:text-accent-text"
      >
        <span className="shrink-0 font-mono text-[11px] text-fg-muted">{item.key}</span>
        <span className="truncate underline-offset-2 group-hover:underline">{item.title}</span>
      </Link>
    </li>
  );
}
