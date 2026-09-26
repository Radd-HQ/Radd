import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
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
  SquareKanban,
  GanttChartSquare,
} from "lucide-react";
import {
  errorMessage,
  isPaletteText,
  usePaletteAnswer,
  usePaletteModes,
  type PaletteMode,
  type PaletteRow,
} from "@radd/plugin-sdk";
import type { LucideIcon } from "lucide-react";
import { useNavFacts } from "../lib/nav-facts";
import { PALETTE_SEARCH_LIMIT, RoutePath, SEARCH_DEBOUNCE_MS } from "../lib/constants";
import { usePermissions } from "../lib/hooks";
import { PageRoute, pagePermalink } from "@radd-plugin-ui/pages/links";
import { pageSearchQuery } from "@radd-plugin-ui/pages/queries";
import type { PageSearchResult } from "@radd-plugin-ui/pages/types";
import { searchQuery, entitySearchQuery } from "../lib/queries";
import { Permission, type EntityHit, type SearchResult } from "../lib/types";
import { NewItemModal } from "./items/NewItemModal";
import { listRecentItems } from "../lib/recent";
import { projectsQuery, projectByKeyQuery } from "@radd-plugin-ui/projects/directory-queries";
import type { Project } from "@radd-plugin-ui/projects/types";

/**
 * Cmd-K command palette (spec 28): quick-open issues via the search module +
 * client-side "Go to" navigation. Opened with Cmd/Ctrl-K anywhere, or
 * programmatically via `openCommandPalette()` (the sidebar Search row).
 * Plugins give it more faces (RADD-1400): a contributed MODE is entered from a
 * trailing palette row and left with Esc/back, never by closing, and answers
 * what is typed with rows (drawn and navigated like the palette's own) or text.
 */

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
 * a contributed mode's entry point, or a row of that mode's answer. */
type PaletteEntry =
  | { kind: "issue"; result: SearchResult }
  | { kind: "doc"; result: PageSearchResult }
  /** RADD-1327: a hit from any other registered searchable (a plugin's entity). */
  | { kind: "entity"; hit: EntityHit; group: string }
  | { kind: "goto"; entry: GotoEntry }
  | { kind: "action"; label: string; project: Project }
  | { kind: "mode"; mode: PaletteMode }
  | { kind: "answer"; row: PaletteRow };

const STATIC_GOTOS: GotoEntry[] = [
  { label: "My Work", icon: House, to: RoutePath.home },
  { label: "Inbox", icon: Inbox, to: RoutePath.inbox },
  { label: "Starred", icon: Star, to: RoutePath.starred },
  { label: "Projects", icon: Layers, to: RoutePath.projects },
  // RADD-1241: the wiki is a destination like the others (gated by facts.docs).
  { label: "Pages", icon: BookOpen, to: PageRoute.pages },
  { label: "Reports", icon: BarChart3, to: RoutePath.reports },
  { label: "Timesheet", icon: Clock, to: RoutePath.timesheet },
  { label: "Settings", icon: Settings, to: RoutePath.settings },
];

/** ts_headline `<b>` marks as React `<mark>`s — split, never innerHTML, so hostile text cannot execute. */
function renderSnippet(snippet: string): ReactNode[] {
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
  // null = the keyword search face; else the id of the contributed mode in use.
  const [modeId, setModeId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [selected, setSelected] = useState(0);
  const [newItemProject, setNewItemProject] = useState<Project | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const perms = usePermissions();

  const { data: projectList } = useQuery({ ...projectsQuery(), enabled: open });
  // The palette mounts above the routes that own `projectKey`, so read the
  // current project off the address: /p/KEY/… or an issue's KEY-123.
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const currentProjectKey =
    /^\/p\/([^/]+)/.exec(pathname)?.[1] ?? /^\/issues\/(.+)-\d+$/.exec(pathname)?.[1];
  // The projects list is capped; the project you are in must never fall off it.
  const { data: currentProject } = useQuery({ ...projectByKeyQuery(currentProjectKey ?? ""), enabled: open && Boolean(currentProjectKey) });
  const projects = useMemo(
    () => (currentProject && !(projectList ?? []).some((p) => p.id === currentProject.id)
      ? [...(projectList ?? []), currentProject] : projectList),
    [projectList, currentProject],
  );
  // The contributed modes the palette may offer; their gates run only while it is open. A mode
  // withdrawn while in use hands the palette back to search.
  const { modes, gates } = usePaletteModes(open);
  const mode = modes.find((candidate) => candidate.id === modeId) ?? null;
  const searching = open && mode === null;
  const { data: searchData } = useQuery(
    searchQuery(searching ? debounced : "", PALETTE_SEARCH_LIMIT),
  );
  // Doc results merged in (spec 43) — a second query, section-headed "Pages".
  const { data: docsData } = useQuery(
    pageSearchQuery(searching ? debounced : "", PALETTE_SEARCH_LIMIT),
  );
  // RADD-1327: every other registered searchable type (a plugin's entities),
  // each answered and ACL-filtered by its owner. Issues and pages keep their
  // dedicated queries above, so they are excluded here.
  const { data: entityData } = useQuery(
    entitySearchQuery(searching ? debounced : "", {
      exclude: "item,page",
      limit: PALETTE_SEARCH_LIMIT,
    }),
  );
  const answered = usePaletteAnswer(open ? mode : null, debounced);

  const backToSearch = () => {
    setModeId(null);
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
      setModeId(null);
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
    const needle = query.trim().toLowerCase();
    // RADD-1294: an empty palette offers the nav and the CURRENT project, not two
    // rows for every project on the instance — typing reaches the rest.
    if (!needle) {
      return [...gated, ...projectEntries.filter((entry) => entry.params?.projectKey === currentProjectKey)];
    }
    return [...gated, ...projectEntries].filter((entry) => entry.label.toLowerCase().includes(needle));
  }, [projects, query, navFacts, currentProjectKey]);

  const issueEntries: PaletteEntry[] = (searchData?.results ?? []).map((result) => ({
    kind: "issue",
    result,
  }));
  const docEntries: PaletteEntry[] = (docsData?.results ?? []).map((result) => ({
    kind: "doc",
    result,
  }));
  const entityEntries: PaletteEntry[] = (entityData?.groups ?? []).flatMap((group) =>
    group.hits.map((hit) => ({ kind: "entity" as const, hit, group: group.label })),
  );
  // Quick actions (spec 37): "New issue in <PROJECT>" for creatable projects.
  const needle = query.trim().toLowerCase();
  // RADD-1294: with nothing typed, only the project you are in (the palette used
  // to open on 123 of these); typing "new" or a key reaches every project.
  const actionEntries: PaletteEntry[] = (projects ?? [])
    .filter((project) => perms.project(project, Permission.itemCreate))
    .filter((project) => needle || project.key === currentProjectKey)
    .map((project) => ({
      kind: "action" as const,
      label: `New issue in ${project.key}`,
      project,
    }))
    .filter((entry) => !needle || entry.label.toLowerCase().includes(needle));
  // Recently viewed issues lead the empty palette: what you most likely want next.
  const recentEntries: PaletteEntry[] = needle
    ? []
    : listRecentItems().slice(0, 6).map((recent) => ({
        kind: "issue" as const,
        result: { item_id: "", project_id: "", key: recent.key, title: recent.title, snippet: null },
      }));
  const gotoEntries: PaletteEntry[] = gotos.map((entry) => ({ kind: "goto", entry }));
  // Each mode's entry point trails the search-face list whenever there's a query.
  const modeEntries: PaletteEntry[] =
    query.trim() !== "" ? modes.map((candidate) => ({ kind: "mode" as const, mode: candidate })) : [];
  const answer = answered.answer;
  const answerRows = answer && !isPaletteText(answer) ? answer.rows : [];
  const answerEntries: PaletteEntry[] = answerRows.map((row) => ({ kind: "answer", row }));
  const entries: PaletteEntry[] =
    mode !== null
      ? answerEntries
      : [...recentEntries, ...issueEntries, ...docEntries, ...entityEntries, ...actionEntries, ...gotoEntries, ...modeEntries];
  const clamped = Math.min(selected, Math.max(entries.length - 1, 0));

  const choose = (entry: PaletteEntry) => {
    // A mode's entry switches the palette's face; it never closes it.
    if (entry.kind === "mode") {
      setModeId(entry.mode.id);
      setSelected(0);
      inputRef.current?.focus();
      return;
    }
    setOpen(false);
    if (entry.kind === "issue") {
      void navigate({ to: RoutePath.issue, params: { itemKey: entry.result.key } });
    } else if (entry.kind === "answer") {
      // The mode's own site-relative address, followed by the router (no reload).
      void navigate({ href: entry.row.href });
    } else if (entry.kind === "doc") {
      void navigate(pagePermalink(entry.result.page_id));
    } else if (entry.kind === "entity") {
      // The owner's own site-relative address — a plugin route the host
      // router may not know by name, so it is followed as a URL.
      if (entry.hit.url) window.location.assign(entry.hit.url);
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
      {gates}
      <div className="animate-menu-in w-full max-w-xl overflow-hidden rounded-lg border border-subtle bg-surface shadow-pop">
        <div className="flex items-center gap-2 border-b border-subtle px-4">
          {mode !== null ? (
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
              // Esc backs out of a mode first; only the search face closes.
              if (event.key === "Escape") {
                if (mode !== null) backToSearch();
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
            placeholder={mode?.placeholder ?? "Search issues, or jump to…"}
            aria-label="Search"
            className="w-full bg-transparent py-3 text-sm text-heading placeholder:text-fg-faint focus:outline-none"
          />
          <kbd className="rounded border border-subtle px-1.5 py-0.5 text-[10px] text-fg-muted">
            esc
          </kbd>
        </div>

        <div className="max-h-[50vh] overflow-y-auto py-1">
          {mode !== null ? (
            <>
              {answer?.heading && (entries.length > 0 || answered.text) && <SectionLabel>{answer.heading}</SectionLabel>}
              {answerEntries.map((entry, index) =>
                entry.kind === "answer" ? (
                  <PaletteRow
                    key={entry.row.id}
                    active={index === clamped}
                    onClick={() => choose(entry)}
                    onHover={() => setSelected(index)}
                  >
                    <AnswerRow row={entry.row} />
                  </PaletteRow>
                ) : null,
              )}
              {answered.text && entries.length === 0 && (
                <p className="whitespace-pre-wrap px-4 py-3 text-[13px] text-fg" data-palette-answer-text>
                  {answered.text}
                </p>
              )}
              {entries.length === 0 && !answered.text && (
                <p className="px-4 py-6 text-center text-sm text-fg-muted">
                  {answered.fetching
                    ? (mode.busyLabel ?? "Searching…")
                    : answered.error
                      ? errorMessage(answered.error)
                      : query.trim() && answer && !isPaletteText(answer)
                        ? (answer.empty ?? "No matches.")
                        : query.trim()
                          ? "No matches."
                          : (mode.prompt ?? "Type to search.")}
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

          {entityEntries.map((entry, index) => {
            const flatIndex = issueEntries.length + docEntries.length + index;
            if (entry.kind !== "entity") return null;
            const first = index === 0 || (entityEntries[index - 1] as { group?: string }).group !== entry.group;
            return (
              <Fragment key={`${entry.hit.entity_type}:${entry.hit.id}`}>
                {first && <SectionLabel>{entry.group}</SectionLabel>}
                <PaletteRow
                  active={flatIndex === clamped}
                  onClick={() => choose(entry)}
                  onHover={() => setSelected(flatIndex)}
                >
                  <Layers size={14} className="shrink-0 text-fg-muted" aria-hidden />
                  <span className="min-w-0 flex-1" data-entity-hit={entry.hit.entity_type}>
                    <span className="block truncate text-[13px] text-fg">{entry.hit.title}</span>
                    {entry.hit.subtitle && (
                      <span className="block truncate text-xs text-fg-muted">{entry.hit.subtitle}</span>
                    )}
                  </span>
                </PaletteRow>
              </Fragment>
            );
          })}

          {actionEntries.length > 0 && <SectionLabel>Actions</SectionLabel>}
          {actionEntries.map((entry, index) => {
            const flatIndex = issueEntries.length + docEntries.length + entityEntries.length + index;
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
              issueEntries.length + docEntries.length + entityEntries.length + actionEntries.length + index;
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

          {/* Each contributed mode's entry point — trails the list so keyword hits stay first. */}
          {modeEntries.map((entry, index) => {
            if (entry.kind !== "mode") return null;
            const flatIndex =
              issueEntries.length + docEntries.length + entityEntries.length + actionEntries.length + gotoEntries.length + index;
            const Icon = entry.mode.icon;
            return (
              <PaletteRow
                key={`mode:${entry.mode.id}`}
                active={flatIndex === clamped}
                onClick={() => choose(entry)}
                onHover={() => setSelected(flatIndex)}
              >
                {Icon ? <Icon size={14} className="shrink-0 text-accent-text" aria-hidden /> : null}
                <span className="truncate text-[13px] text-fg">
                  {entry.mode.label}: “{query.trim()}”{" "}
                  <span className="text-fg-muted">— {entry.mode.hint}</span>
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

/** A row of a mode's answer, in the palette's own row anatomy. */
function AnswerRow({ row }: { row: PaletteRow }) {
  const Icon = row.icon;
  return (
    <>
      {Icon ? <Icon size={14} className="shrink-0 text-fg-muted" aria-hidden /> : null}
      {row.badge ? (
        <span className="shrink-0 rounded bg-elevated px-1.5 font-mono text-[11px] text-fg-secondary">{row.badge}</span>
      ) : null}
      {row.subtitle ? (
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] text-fg">{row.title}</span>
          <span className="block truncate text-xs text-fg-muted">{row.subtitle}</span>
        </span>
      ) : (
        <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{row.title}</span>
      )}
      {row.hint ? <span className="shrink-0 text-[10px] text-fg-faint">{row.hint}</span> : null}
    </>
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
