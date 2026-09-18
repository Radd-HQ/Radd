import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  BarChart3,
  BookOpen,
  Clock,
  House,
  Inbox,
  Star,
  Layers,
  Plus,
  Search,
  Settings,
  Sparkles,
  SquareKanban,
  GanttChartSquare,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useNavFacts } from "../lib/nav-facts";
import { PALETTE_SEARCH_LIMIT, RoutePath, SEARCH_DEBOUNCE_MS } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { pagePermalink } from "../lib/page-links";
import {
  aiStatusQuery,
  pageSearchQuery,
  projectsQuery,
  searchQuery,
  semanticSearchQuery,
} from "../lib/queries";
import {
  AiFeature,
  Permission,
  type PageSearchResult,
  type Project,
  type SearchResult,
  type SemanticDoc,
  type SemanticItem,
} from "../lib/types";
import { NewItemModal } from "./items/NewItemModal";

/**
 * Cmd-K command palette (spec 28): quick-open issues via the search module +
 * client-side "Go to" navigation. Opened with Cmd/Ctrl-K anywhere, or
 * programmatically via `openCommandPalette()` (the sidebar Search row).
 * Spec 103 adds an Ask mode — "search by meaning" over GET /search/semantic —
 * entered from a trailing palette row and left with Esc/back, never by closing.
 */

/** The palette's two faces: keyword search vs the semantic Ask results. */
const PaletteMode = {
  search: "search",
  ask: "ask",
} as const;
type PaletteModeValue = (typeof PaletteMode)[keyof typeof PaletteMode];

type Listener = () => void;
const openListeners = new Set<Listener>();

export function openCommandPalette() {
  for (const listener of openListeners) listener();
}

interface GotoEntry {
  label: string;
  icon: LucideIcon;
  to: string;
  params?: Record<string, string>;
}

/** A selectable palette row: an issue/doc hit, a navigation target, an action,
 * the Ask-mode entry point, or a semantic match. */
type PaletteEntry =
  | { kind: "issue"; result: SearchResult }
  | { kind: "doc"; result: PageSearchResult }
  | { kind: "goto"; entry: GotoEntry }
  | { kind: "action"; label: string; project: Project }
  | { kind: "ask" }
  | { kind: "semantic-item"; result: SemanticItem }
  | { kind: "semantic-doc"; result: SemanticDoc };

const STATIC_GOTOS: GotoEntry[] = [
  { label: "My Work", icon: House, to: RoutePath.home },
  { label: "Inbox", icon: Inbox, to: RoutePath.inbox },
  { label: "Starred", icon: Star, to: RoutePath.starred },
  { label: "Projects", icon: Layers, to: RoutePath.projects },
  // RADD-1241: the wiki is a destination like the others (gated by facts.docs).
  { label: "Pages", icon: BookOpen, to: RoutePath.pages },
  { label: "Reports", icon: BarChart3, to: RoutePath.reports },
  { label: "Timesheet", icon: Clock, to: RoutePath.timesheet },
  { label: "Settings", icon: Settings, to: RoutePath.settings },
];

/**
 * Snippets arrive with ts_headline's `<b>…</b>` marks. Rendered WITHOUT
 * innerHTML: split on the markers and emit text + <mark> nodes, so hostile
 * text in titles/comments can never execute (worst case a literal "<b>" in
 * a comment reads as a highlight boundary).
 */
/** ts_headline's <b> markers as React <mark>s — shared with the public KB
 * search (RADD-1099), never innerHTML. */
export function renderSnippet(snippet: string): ReactNode[] {
  return snippet.split("<b>").flatMap((chunk, index) => {
    if (index === 0) return [chunk];
    const [marked, ...rest] = chunk.split("</b>");
    return [
      <mark key={index} className="rounded-sm bg-accent/30 px-0.5 text-accent-text-strong">
        {marked}
      </mark>,
      rest.join("</b>"),
    ];
  });
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<PaletteModeValue>(PaletteMode.search);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selected, setSelected] = useState(0);
  const [newItemProject, setNewItemProject] = useState<Project | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const perms = usePermissions();

  const { data: projects } = useQuery({ ...projectsQuery(), enabled: open });
  const { data: searchData } = useQuery(
    searchQuery(open && mode === PaletteMode.search ? debounced : "", PALETTE_SEARCH_LIMIT),
  );
  // Doc results merged in (spec 43) — a second query, section-headed "Pages".
  const { data: docsData } = useQuery(
    pageSearchQuery(open && mode === PaletteMode.search ? debounced : "", PALETTE_SEARCH_LIMIT),
  );
  // Ask mode (spec 103): the affordance gates on the semantic_search feature
  // flag; the response's own `enabled` catches it going dormant mid-session.
  const { data: aiStatus } = useQuery({ ...aiStatusQuery, enabled: open });
  const askAvailable = Boolean(aiStatus?.enabled && aiStatus.features[AiFeature.semanticSearch]);
  const semantic = useQuery(
    semanticSearchQuery(open && mode === PaletteMode.ask ? debounced : ""),
  );

  const backToSearch = () => {
    setMode(PaletteMode.search);
    setSelected(0);
    inputRef.current?.focus();
  };

  // Global hotkey + programmatic open.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
        return;
      }
      // Bare "/" opens too (spec 32) — but never while typing somewhere.
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        const typing =
          target instanceof HTMLInputElement ||
          target instanceof HTMLTextAreaElement ||
          target instanceof HTMLSelectElement ||
          Boolean(target?.isContentEditable);
        if (!typing) {
          event.preventDefault();
          setOpen(true);
        }
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKeyDown);
    openListeners.add(onOpen);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      openListeners.delete(onOpen);
    };
  }, []);

  // Reset + focus on open; debounce the search text while typing.
  useEffect(() => {
    if (open) {
      setMode(PaletteMode.search);
      setQuery("");
      setDebounced("");
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const navFacts = useNavFacts();
  const gotos = useMemo<GotoEntry[]>(() => {
    const projectEntries = (projects ?? []).flatMap<GotoEntry>((project) => [
      {
        label: `${project.key} · Project`,
        icon: SquareKanban,
        to: RoutePath.project,
        params: { projectKey: project.key },
      },
      {
        label: `${project.key} · Roadmap`,
        icon: GanttChartSquare,
        to: RoutePath.roadmap,
        params: { projectKey: project.key },
      },
    ]);
    // RADD-843: the palette IS the nav — same predicate as sidebar/rail/pins.
    const gated = STATIC_GOTOS.filter((entry) => navFacts.forPath(entry.to));
    const all = [...gated, ...projectEntries];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((entry) => entry.label.toLowerCase().includes(needle));
  }, [projects, query, navFacts]);

  const issueEntries: PaletteEntry[] = (searchData?.results ?? []).map((result) => ({
    kind: "issue",
    result,
  }));
  const docEntries: PaletteEntry[] = (docsData?.results ?? []).map((result) => ({
    kind: "doc",
    result,
  }));
  // Quick actions (spec 37): "New issue in <PROJECT>" for creatable projects.
  const needle = query.trim().toLowerCase();
  const actionEntries: PaletteEntry[] = (projects ?? [])
    .filter((project) => perms.project(project, Permission.itemCreate))
    .map((project) => ({
      kind: "action" as const,
      label: `New issue in ${project.key}`,
      project,
    }))
    .filter((entry) => !needle || entry.label.toLowerCase().includes(needle));
  const gotoEntries: PaletteEntry[] = gotos.map((entry) => ({ kind: "goto", entry }));
  // The Ask entry point trails the search-mode list whenever there's a query.
  const askEntries: PaletteEntry[] =
    askAvailable && query.trim() !== "" ? [{ kind: "ask" }] : [];
  const semanticItemEntries: PaletteEntry[] = (semantic.data?.items ?? []).map((result) => ({
    kind: "semantic-item",
    result,
  }));
  const semanticDocEntries: PaletteEntry[] = (semantic.data?.docs ?? []).map((result) => ({
    kind: "semantic-doc",
    result,
  }));
  const entries: PaletteEntry[] =
    mode === PaletteMode.ask
      ? [...semanticItemEntries, ...semanticDocEntries]
      : [...issueEntries, ...docEntries, ...actionEntries, ...gotoEntries, ...askEntries];
  const clamped = Math.min(selected, Math.max(entries.length - 1, 0));

  const choose = (entry: PaletteEntry) => {
    // Ask switches the palette's face; it never closes it.
    if (entry.kind === "ask") {
      setMode(PaletteMode.ask);
      setSelected(0);
      inputRef.current?.focus();
      return;
    }
    setOpen(false);
    if (entry.kind === "issue") {
      void navigate({ to: RoutePath.issue, params: { itemKey: entry.result.key } });
    } else if (entry.kind === "semantic-item") {
      void navigate({ to: RoutePath.issue, params: { itemKey: entry.result.key } });
    } else if (entry.kind === "doc") {
      void navigate(pagePermalink(entry.result.page_id));
    } else if (entry.kind === "semantic-doc") {
      void navigate(pagePermalink(entry.result.page_id));
    } else if (entry.kind === "action") {
      setNewItemProject(entry.project);
    } else {
      void navigate({ to: entry.entry.to, params: entry.entry.params ?? {} });
    }
  };

  if (!open) {
    return newItemProject ? (
      <NewItemModal project={newItemProject} onClose={() => setNewItemProject(null)} />
    ) : null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 pt-[15vh]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div className="animate-menu-in w-full max-w-xl overflow-hidden rounded-lg border border-subtle bg-surface shadow-pop">
        <div className="flex items-center gap-2 border-b border-subtle px-4">
          {mode === PaletteMode.ask ? (
            <button
              type="button"
              onClick={backToSearch}
              aria-label="Back to search"
              title="Back to search (Esc)"
              className="-ml-1 shrink-0 rounded p-0.5 text-fg-muted hover:bg-elevated hover:text-fg cursor-pointer"
            >
              <ArrowLeft size={15} aria-hidden />
            </button>
          ) : (
            <Search size={15} className="shrink-0 text-fg-muted" aria-hidden />
          )}
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setSelected(0);
            }}
            onKeyDown={(event) => {
              // Esc backs out of Ask mode first; only search mode closes.
              if (event.key === "Escape") {
                if (mode === PaletteMode.ask) backToSearch();
                else setOpen(false);
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                setSelected((current) => Math.min(current + 1, entries.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setSelected((current) => Math.max(current - 1, 0));
              } else if (event.key === "Enter" && entries[clamped]) {
                choose(entries[clamped]);
              }
            }}
            placeholder={
              mode === PaletteMode.ask ? "Search by meaning…" : "Search issues, or jump to…"
            }
            aria-label="Search"
            className="w-full bg-transparent py-3 text-sm text-heading placeholder:text-fg-faint focus:outline-none"
          />
          <kbd className="rounded border border-subtle px-1.5 py-0.5 text-[10px] text-fg-muted">
            esc
          </kbd>
        </div>

        <div className="max-h-[50vh] overflow-y-auto py-1">
          {mode === PaletteMode.ask ? (
            <>
              {entries.length > 0 && <SectionLabel>Semantic matches</SectionLabel>}
              {semanticItemEntries.map((entry, index) => (
                <PaletteRow
                  key={entry.kind === "semantic-item" ? entry.result.item_id : index}
                  active={index === clamped}
                  onClick={() => choose(entry)}
                  onHover={() => setSelected(index)}
                >
                  {entry.kind === "semantic-item" && (
                    <>
                      <span className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary">
                        {entry.result.key}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-[13px] text-fg">
                        {entry.result.title}
                      </span>
                      <span className="shrink-0 text-[10px] text-fg-faint">
                        {Math.round(entry.result.score * 100)}%
                      </span>
                    </>
                  )}
                </PaletteRow>
              ))}
              {semanticDocEntries.map((entry, index) => {
                const flatIndex = semanticItemEntries.length + index;
                return (
                  <PaletteRow
                    key={entry.kind === "semantic-doc" ? entry.result.page_id : flatIndex}
                    active={flatIndex === clamped}
                    onClick={() => choose(entry)}
                    onHover={() => setSelected(flatIndex)}
                  >
                    {entry.kind === "semantic-doc" && (
                      <>
                        <BookOpen size={14} className="shrink-0 text-fg-muted" aria-hidden />
                        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">
                          {entry.result.title}
                        </span>
                        <span className="shrink-0 text-[10px] text-fg-faint">
                          {Math.round(entry.result.score * 100)}%
                        </span>
                      </>
                    )}
                  </PaletteRow>
                );
              })}
              {entries.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-fg-muted">
                  {semantic.isFetching
                    ? "Searching…"
                    : semantic.data && !semantic.data.enabled
                      ? "Semantic search isn't available."
                      : query.trim()
                        ? "Nothing similar found."
                        : "Type to search by meaning."}
                </p>
              )}
            </>
          ) : (
            <>
          {issueEntries.length > 0 && <SectionLabel>Issues</SectionLabel>}
          {issueEntries.map((entry, index) => (
            <PaletteRow
              key={entry.kind === "issue" ? entry.result.item_id : index}
              active={index === clamped}
              onClick={() => choose(entry)}
              onHover={() => setSelected(index)}
            >
              {entry.kind === "issue" && (
                <>
                  <span className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary">
                    {entry.result.key}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] text-fg">
                      {entry.result.title}
                    </span>
                    {entry.result.snippet && (
                      <span className="block truncate text-xs text-fg-muted">
                        {renderSnippet(entry.result.snippet)}
                      </span>
                    )}
                  </span>
                </>
              )}
            </PaletteRow>
          ))}

          {docEntries.length > 0 && <SectionLabel>Pages</SectionLabel>}
          {docEntries.map((entry, index) => {
            const flatIndex = issueEntries.length + index;
            return (
              <PaletteRow
                key={entry.kind === "doc" ? entry.result.page_id : flatIndex}
                active={flatIndex === clamped}
                onClick={() => choose(entry)}
                onHover={() => setSelected(flatIndex)}
              >
                {entry.kind === "doc" && (
                  <>
                    <BookOpen size={14} className="shrink-0 text-fg-muted" aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-fg">
                        {entry.result.title}
                      </span>
                      {entry.result.snippet && (
                        <span className="block truncate text-xs text-fg-muted">
                          {renderSnippet(entry.result.snippet)}
                        </span>
                      )}
                    </span>
                  </>
                )}
              </PaletteRow>
            );
          })}

          {actionEntries.length > 0 && <SectionLabel>Actions</SectionLabel>}
          {actionEntries.map((entry, index) => {
            const flatIndex = issueEntries.length + docEntries.length + index;
            return (
              <PaletteRow
                key={entry.kind === "action" ? entry.label : flatIndex}
                active={flatIndex === clamped}
                onClick={() => choose(entry)}
                onHover={() => setSelected(flatIndex)}
              >
                <Plus size={14} className="shrink-0 text-fg-muted" aria-hidden />
                <span className="truncate text-[13px] text-fg">
                  {entry.kind === "action" ? entry.label : null}
                </span>
              </PaletteRow>
            );
          })}

          {gotoEntries.length > 0 && <SectionLabel>Go to</SectionLabel>}
          {gotoEntries.map((entry, index) => {
            const flatIndex =
              issueEntries.length + docEntries.length + actionEntries.length + index;
            const Icon = entry.kind === "goto" ? entry.entry.icon : Layers;
            return (
              <PaletteRow
                key={entry.kind === "goto" ? entry.entry.label : flatIndex}
                active={flatIndex === clamped}
                onClick={() => choose(entry)}
                onHover={() => setSelected(flatIndex)}
              >
                <Icon size={14} className="shrink-0 text-fg-muted" aria-hidden />
                <span className="truncate text-[13px] text-fg">
                  {entry.kind === "goto" ? entry.entry.label : null}
                </span>
              </PaletteRow>
            );
          })}

          {/* Ask mode entry point (spec 103) — trails the list so keyword hits stay first. */}
          {askEntries.map((entry) => {
            const flatIndex =
              issueEntries.length + docEntries.length + actionEntries.length + gotoEntries.length;
            return (
              <PaletteRow
                key="ask"
                active={flatIndex === clamped}
                onClick={() => choose(entry)}
                onHover={() => setSelected(flatIndex)}
              >
                <Sparkles size={14} className="shrink-0 text-accent-text" aria-hidden />
                <span className="truncate text-[13px] text-fg">
                  Ask: “{query.trim()}”{" "}
                  <span className="text-fg-muted">— search by meaning</span>
                </span>
              </PaletteRow>
            );
          })}

          {entries.length === 0 && (
            <p className="px-4 py-6 text-center text-sm text-fg-muted">
              {query.trim() ? "No matches." : "Type to search."}
            </p>
          )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-4 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-fg-faint">
      {children}
    </p>
  );
}

function PaletteRow({
  active,
  onClick,
  onHover,
  children,
}: {
  active: boolean;
  onClick: () => void;
  onHover: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseMove={onHover}
      className={
        "flex w-full items-center gap-2.5 px-4 py-2 text-left cursor-pointer " +
        (active ? "bg-accent/15" : "hover:bg-overlay")
      }
    >
      {children}
    </button>
  );
}
