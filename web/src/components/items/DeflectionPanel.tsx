import { useQuery } from "@tanstack/react-query";
import { BookOpen, CheckCircle2 } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { DEFLECT_DEBOUNCE_MS, DEFLECT_MIN_QUERY_CHARS, RoutePath } from "../../lib/constants";
import { useDebounced, useOpenIssueRef } from "../../lib/hooks";
import { deflectQuery } from "../../lib/queries";
import type { DeflectDoc, DeflectItem } from "../../lib/types";

interface DeflectionPanelProps {
  /** The half-typed issue title driving the lookup. */
  query: string;
  projectId: string;
}

/**
 * KB deflection (spec 66): while the reporter types a title, surface wiki
 * pages that may already answer it and previously RESOLVED issues, so they can
 * stop filing. Debounced; renders nothing until the query is long enough and
 * something matches. Issue rows open in the PEEK (the half-typed form survives
 * the detour); doc rows open in a new tab (there is no doc peek). NOT mounted
 * on the PUBLIC form page (the endpoint is authenticated; that page has its
 * own tokened panel).
 */
export function DeflectionPanel({ query, projectId }: DeflectionPanelProps) {
  const debounced = useDebounced(query, DEFLECT_DEBOUNCE_MS);
  const deflect = useQuery(deflectQuery(debounced, projectId));
  const docs = deflect.data?.docs ?? [];
  const items = deflect.data?.items ?? [];
  // Gate on the LIVE query too — kept-previous data must not outlive a cleared title.
  if (query.trim().length < DEFLECT_MIN_QUERY_CHARS) return null;
  if (docs.length === 0 && items.length === 0) return null;

  return (
    <div className="flex flex-col gap-2.5 rounded-md border border-subtle bg-surface/40 p-2.5">
      <DeflectDocsSection docs={docs} />
      <DeflectItemsSection items={items} />
    </div>
  );
}

/** Wiki pages that may already answer it — shared by the authed panels and,
 * with `kb`, the public form's panel (which links the public /kb routes). */
export function DeflectDocsSection({ docs, kb = false }: { docs: DeflectDoc[]; kb?: boolean }) {
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
              to={kb ? RoutePath.kbPage : RoutePath.docPage}
              params={{ spaceId: doc.space_id, pageId: doc.id }}
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
          <li key={item.key}>
            <Link
              to={RoutePath.issue}
              params={{ itemKey: item.key }}
              onClick={(event) => void openRef(item.key, event)}
              className="group flex items-baseline gap-1.5 text-xs text-fg hover:text-accent-text"
            >
              <span className="shrink-0 font-mono text-[11px] text-fg-muted">{item.key}</span>
              <span className="truncate underline-offset-2 group-hover:underline">
                {item.title}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
