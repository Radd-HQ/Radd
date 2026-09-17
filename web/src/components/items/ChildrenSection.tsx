import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Plus, Square, SquareCheckBig } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { api, errorMessage } from "../../lib/api";
import { Entity, invalidateEntities } from "../../lib/cache";
import { ApiPath, RoutePath, apiItemPath } from "../../lib/constants";
import { useOpenIssueRef, usePermissions } from "../../lib/hooks";
import { CATEGORY_META } from "../../lib/meta";
import { childItemPagesQuery, statesQuery } from "../../lib/queries";
import {
  ItemKind,
  Permission,
  StateCategory,
  type Item,
  type ItemRollup,
  type Project,
} from "../../lib/types";
import { Avatar } from "../Avatar";
import { formatPoints } from "./ItemBadges";
import { Spinner } from "../Spinner";
import { ErrorText } from "../ErrorText";

/**
 * An item's children, on the item (RADD-655, RADD-660).
 *
 * One component covers both levels because the question is the same at each:
 * an epic lists its issues, an issue lists its subtasks. What differs is the
 * WEIGHT — a subtask is a checklist line with a tick box, an issue is a row you
 * click through to — so the checkbox appears only for subtask children.
 *
 * Open work sorts first. The most common question an epic raises is "what is
 * left", and that should be answered by looking at the top rather than by
 * reading the whole list.
 */
export function ChildrenSection({
  item,
  project,
  rollup,
  showPoints = false,
}: {
  item: Item;
  project: Project;
  rollup: ItemRollup | undefined;
  showPoints?: boolean;
}) {
  const perms = usePermissions();
  const canWrite = perms.project(project, Permission.itemUpdate);
  const canCreate = perms.project(project, Permission.itemCreate);
  const [expanded, setExpanded] = useState(false);

  const childKind = item.kind === ItemKind.epic ? ItemKind.issue : ItemKind.subtask;
  const isChecklist = childKind === ItemKind.subtask;
  const children = useInfiniteQuery({ ...childItemPagesQuery(item.id), enabled: expanded });
  const childRows = [...new Map((children.data?.pages.flatMap(page=>page.rows) ?? []).map(item=>[item.id,item])).values()];

  // The rollup counts EVERY descendant; the list shows direct children. When the
  // card is collapsed the rollup is the only number available, so it is what the
  // header shows — expanding refines it rather than contradicting it.
  const total = rollup?.total ?? item.child_count ?? 0;
  const done = rollup?.done ?? 0;
  const inProgress = rollup?.in_progress ?? 0;
  if (total === 0 && !canCreate) return null;

  return (
    <section className="rounded-xl border border-subtle bg-surface p-4 shadow-lift">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 text-left cursor-pointer"
      >
        <ChevronRight
          size={14}
          aria-hidden
          className={`shrink-0 text-fg-muted transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">
          {isChecklist ? "Subtasks" : "Epic progress"}
        </h3>
        {total > 0 && (
          <span className="text-[11px] tabular-nums text-fg-muted">
            {done}/{total} done
          </span>
        )}
        {inProgress > 0 && (
          <span className="text-[11px] tabular-nums text-accent-text">
            {inProgress} in progress
          </span>
        )}
        {showPoints && (rollup?.points_total ?? 0) > 0 && (
          <span className="text-[11px] tabular-nums text-fg-muted">
            {formatPoints(rollup!.points_done)} pts of {formatPoints(rollup!.points_total)}
          </span>
        )}
        {total > 0 && (
          <span
            className="ml-auto inline-flex h-1.5 w-32 overflow-hidden rounded-full bg-elevated"
            aria-hidden
          >
            <span
              className="h-full bg-chart-progress"
              style={{ width: `${Math.round((done / total) * 100)}%` }}
            />
            <span
              className="h-full bg-accent/60"
              style={{ width: `${Math.round((inProgress / Math.max(total, 1)) * 100)}%` }}
            />
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-3">
          {children.isPending ? (
            <Spinner label="Loading children…" />
          ) : children.isError && !children.data ? (
            <ErrorText error={children.error} />
          ) : childRows.length === 0 ? (
            <p className="text-[13px] text-fg-faint">
              {isChecklist ? "No subtasks yet." : "No child items yet."}
            </p>
          ) : (
            <ChildList
              items={childRows}
              project={project}
              checklist={isChecklist}
              canWrite={canWrite}
            />
          )}
          {children.hasNextPage && <button className="mt-2 text-xs text-accent-text underline" disabled={children.isFetchingNextPage}
            onClick={() => void children.fetchNextPage()}>{children.isFetchingNextPage ? "Loading…" : "Show 50 more children"}</button>}
          {children.isFetchNextPageError && <p role="alert" className="text-xs text-fg-muted">Could not load more children. Try again.</p>}
          {canCreate && <QuickAdd parent={item} project={project} childKind={childKind} />}
        </div>
      )}
    </section>
  );
}

function ChildList({
  items,
  project,
  checklist,
  canWrite,
}: {
  items: Item[];
  project: Project;
  checklist: boolean;
  canWrite: boolean;
}) {
  // Workflow category/state order is applied on the server before pagination.
  const sorted = items;
  return (
    <ul className="flex flex-col">
      {sorted.map((child) => (
        <ChildRow
          key={child.id}
          child={child}
          project={project}
          checklist={checklist}
          canWrite={canWrite}
        />
      ))}
    </ul>
  );
}

function ChildRow({
  child,
  project,
  checklist,
  canWrite,
}: {
  child: Item;
  project: Project;
  checklist: boolean;
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const openRef = useOpenIssueRef();
  const states = useQuery({ ...statesQuery(project.id), enabled: checklist });
  const isDone =
    child.state.category === StateCategory.done ||
    child.state.category === StateCategory.canceled;

  const toggle = useMutation({
    mutationFn: () => {
      const list = states.data ?? [];
      // Ticking moves to the project's first done state; unticking returns the
      // subtask to the first state that is not finished, whatever the project
      // calls those.
      const target = isDone
        ? list.find((state) => CATEGORY_META[state.category].order < CATEGORY_META[StateCategory.done].order)
        : list.find((state) => state.category === StateCategory.done);
      if (!target) throw new Error("this project has no state to move to");
      return api.patch<Item>(apiItemPath(child.id), { state_id: target.id });
    },
    onSettled: () => void invalidateEntities(queryClient, Entity.item),
  });

  return (
    <li className="group/child flex items-center gap-2 border-b border-subtle/60 py-1.5 last:border-b-0">
      {checklist && (
        <button
          type="button"
          onClick={() => toggle.mutate()}
          disabled={!canWrite || toggle.isPending || states.isPending}
          // Spec 96: un-writable controls are DISABLED with a reason, not hidden.
          title={canWrite ? (isDone ? "Mark as not done" : "Mark as done") : "You cannot edit items in this project"}
          aria-label={isDone ? `Reopen ${child.key}` : `Complete ${child.key}`}
          className="shrink-0 rounded p-0.5 text-fg-muted hover:text-fg cursor-pointer disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isDone ? (
            <SquareCheckBig size={15} className="text-chart-progress" aria-hidden />
          ) : (
            <Square size={15} aria-hidden />
          )}
        </button>
      )}
      {/* RADD-699: a child opens in PEEK over what you are reading — surveying an
          epic should not cost you the epic. `useOpenIssueRef` also handles the
          from-inside-a-peek case (promote the parent, peek the child) and leaves
          modified clicks to the browser, which is why the real href stays. */}
      <Link
        to={RoutePath.issue}
        params={{ itemKey: child.key }}
        onClick={(event) => void openRef(child.key, event)}
        className="flex min-w-0 flex-1 items-center gap-2 text-[13px] hover:underline"
      >
        <span className="shrink-0 font-mono text-[11px] text-fg-faint">{child.key}</span>
        <span className={`truncate ${isDone ? "text-fg-muted line-through" : "text-fg"}`}>
          {child.title}
        </span>
      </Link>
      {!checklist && (
        <span
          className={`shrink-0 rounded border px-1.5 py-px text-[11px] ${
            CATEGORY_META[child.state.category].pillClassName
          }`}
        >
          {child.state.name}
        </span>
      )}
      {child.assignee && (
        <Avatar user={child.assignee} size="xs" className="shrink-0" />
      )}
    </li>
  );
}

/** One input, Enter to append — five subtasks should cost five lines of typing. */
function QuickAdd({
  parent,
  project,
  childKind,
}: {
  parent: Item;
  project: Project;
  childKind: string;
}) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.post<Item>(ApiPath.items, {
        project_id: project.id,
        parent_id: parent.id,
        kind: childKind,
        title: title.trim(),
      }),
    onSuccess: () => {
      setTitle("");
      void invalidateEntities(queryClient, Entity.item);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (title.trim()) create.mutate();
  };

  return (
    <form onSubmit={onSubmit} className="mt-2 flex items-center gap-2">
      <Plus size={13} className="shrink-0 text-fg-faint" aria-hidden />
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        placeholder={childKind === ItemKind.subtask ? "Add a subtask…" : "Add a child item…"}
        aria-label={childKind === ItemKind.subtask ? "Add a subtask" : "Add a child item"}
        className="h-7 flex-1 rounded-md border border-subtle bg-base px-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      {/* `errorMessage` speaks spec-119 findings, so a child refused by a
          required check reads as the check's own sentence rather than the bare
          "item validation failed" headline, which names no problem and suggests
          no fix. (The quick-add posts straight to `POST /items` deliberately —
          one input and Enter is the whole feature, and the enforcement path is
          what makes a required rule apply to it at all.) */}
      {create.isError && (
        <span className="text-[11px] text-status-danger-ink">{errorMessage(create.error)}</span>
      )}
    </form>
  );
}
