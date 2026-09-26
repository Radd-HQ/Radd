import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { Archive, ArchiveRestore, Download, History, Link2, Lock, Printer, Trash2 } from "lucide-react";
import {
  API_BASE, Callout, DropdownMenu, EditingNow, IconButton, relativeTime, type AvatarUser, type LivePerson,
} from "@radd/plugin-sdk";
import { pageExportPath } from "../endpoints";
import { PageRoute, pagePermalink, pagePrintHref } from "../links";
import type { Page } from "../types";
import { PageWatchButton } from "./PageWatchButton";

export const PageTab = { content: "content", history: "history" } as const;
export type PageTabValue = (typeof PageTab)[keyof typeof PageTab];

/** RADD-1228: an archived page is read-only and hidden from the tree until restored. */
export function ArchivedBanner({ spaceSlug, canManage, onRestore }: {
  spaceSlug?: string; canManage: boolean; onRestore: () => void;
}) {
  return (
    <Callout kind="warning" icon={Archive} className="mb-3" data-archived-banner>
      <div className="flex flex-wrap items-center gap-2">
        <span>This page is archived — read-only and hidden from the tree until restored.</span>
        {canManage && spaceSlug && (
          <Link to={PageRoute.space} params={{ spaceSlug }} search={{ archived: true }} className="underline-offset-2 hover:underline">
            All archived pages
          </Link>
        )}
        {canManage && (
          <button type="button" onClick={onRestore}
            className="ml-auto flex items-center gap-1 rounded border border-callout-warning-border/60 px-1.5 py-0.5 hover:bg-callout-warning-border/10 cursor-pointer">
            <ArchiveRestore size={12} aria-hidden />
            Restore
          </button>
        )}
      </div>
    </Callout>
  );
}

/**
 * The line under the title: who last changed the page, its version and permalink, who is in the
 * room, the Content/History tabs, and the page's actions.
 */
export function PageMeta({
  page, users, people, tab, onTab, authenticated, canWrite, canManage, spaceSlug,
  onChangeUrl, onRestrict, onArchive, onDelete,
}: {
  page: Page;
  users?: AvatarUser[];
  people: LivePerson[];
  tab: PageTabValue;
  onTab: (tab: PageTabValue) => void;
  authenticated: boolean;
  canWrite: boolean;
  canManage: boolean;
  spaceSlug?: string;
  onChangeUrl: () => void;
  onRestrict: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const author = users?.find((user) => user.id === page.updated_by);
  /** RADD-733: a new tab, so the reader keeps their place — the print view replaces the whole
   *  document and the browser's print dialog blocks it. */
  const openPrint = (subpages: boolean) => {
    if (spaceSlug) window.open(pagePrintHref(spaceSlug, page.path, subpages), "_blank", "noopener");
  };
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 px-1.5 text-xs text-fg-muted">
      <span className="min-w-0 break-words">
        Updated by {author?.name ?? "someone"}{" "}
        <span title={page.updated_at}>{relativeTime(page.updated_at)}</span>
      </span>
      <span className="shrink-0 rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary">v{page.version}</span>
      {/* RADD-1233: the page's number IS its permalink — shown where the version is, so the
          stable address is one right-click away. */}
      <Link {...pagePermalink(page.number)} data-page-number={page.number} title="Permanent link — survives renames and moves"
        className="shrink-0 rounded bg-elevated px-1.5 py-px font-mono text-[10px] text-fg-secondary hover:text-fg">
        #{page.number}
      </Link>
      <EditingNow people={people} users={users} className="ml-1" />
      <span className="ml-auto flex flex-wrap items-center gap-1">
        <TabButton active={tab === PageTab.content} onClick={() => onTab(PageTab.content)} label="Content" />
        {/* RADD-1153: versions and watching are account-only reads/writes — a visitor gets neither
            control rather than one that 401s. */}
        {authenticated && (
          <TabButton active={tab === PageTab.history} onClick={() => onTab(PageTab.history)} label="History"
            icon={<History size={11} aria-hidden />} />
        )}
        {authenticated && <PageWatchButton pageId={page.id} />}
        {canWrite && (
          <IconButton onClick={onChangeUrl} title="Change this page's URL" aria-label="Change URL" className="flex">
            <Link2 size={13} aria-hidden />
          </IconButton>
        )}
        {/* RADD-738: the export entry point, with the subpages choice offered WHERE the action is
            taken rather than buried in settings. */}
        <DropdownMenu label="Export this page" align="end" className="ml-1" widthClass="w-56"
          trigger={({ ref, toggle }) => (
            <IconButton ref={ref} onClick={toggle} title="Export as PDF" aria-label="Export this page" className="flex">
              <Printer size={13} aria-hidden />
            </IconButton>
          )}
          items={[
            { kind: "action", label: "Export as PDF", icon: Printer, onSelect: () => openPrint(false) },
            { kind: "action", label: "Export as PDF, with subpages", icon: Printer, onSelect: () => openPrint(true) },
            { kind: "separator" },
            {
              kind: "action", label: "Download as markdown (.zip)", icon: Download,
              // RADD-721: a plain navigation, so the browser's own download handling applies —
              // Content-Disposition names the file.
              onSelect: () => { window.location.href = `${API_BASE}${pageExportPath(page.id)}`; },
            },
          ]}
        />
        {/* RADD-792/793: restrict this ONE page, over the generic spec-92 editor. Offered where the
            page is, not in settings — the decision is about this page and is made while reading it. */}
        {canManage && (
          <IconButton onClick={onRestrict} title="Restrict who can see this page" aria-label="Restrict page" className="ml-1">
            <Lock size={13} aria-hidden />
          </IconButton>
        )}
        {canWrite && (
          <IconButton onClick={onArchive} title="Archive — hidden from the tree until restored" aria-label="Archive page" className="ml-1">
            <Archive size={13} aria-hidden />
          </IconButton>
        )}
        {/* RADD-1245 (radd-hq/radd#17): offered on a LIVE page as well, the way an issue's Delete
            is — archive stays the reversible choice beside it. The server still refuses a page
            with live children. */}
        {canManage && (
          <IconButton danger onClick={onDelete} title="Delete permanently" aria-label="Delete page permanently" className="ml-1">
            <Trash2 size={13} aria-hidden />
          </IconButton>
        )}
      </span>
    </div>
  );
}

function TabButton({ active, onClick, label, icon }: {
  active: boolean; onClick: () => void; label: string; icon?: ReactNode;
}) {
  return (
    <button type="button" onClick={onClick}
      className={"flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium cursor-pointer " +
        (active ? "bg-elevated text-heading" : "text-fg-muted hover:text-fg")}>
      {icon}
      {label}
    </button>
  );
}
