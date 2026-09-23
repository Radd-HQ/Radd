import { Link } from "@tanstack/react-router";
import { CalendarClock, CornerDownRight, Flag, Globe, Rocket, RefreshCw, Star, Users } from "lucide-react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { RoutePath } from "../../lib/constants";
import { ItemVisibility, type ItemVisibilityValue } from "../../lib/types";
import { shortDate } from "../../lib/dates";
import {
  CATEGORY_META,
  CYCLE_STATUS_META,
  KIND_META,
  NO_KIND_ICON,
  PRIORITY_META,
  RELEASE_STATUS_META,
  VISIBILITY_META,
} from "../../lib/meta";
import type {
  CycleRef,
  ItemKindValue,
  ItemParentRef,
  PriorityValue,
  ReleaseRef,
  StateRef,
  TeamRef,
  TypeRef,
  UserRef,
} from "../../lib/types";
import { Avatar } from "../Avatar";
import { ValueChip } from "./ValueChip";

/** Small presentational atoms shared by board cards, list rows, and the detail panel. */

/** The issue key as a REAL link to the full issue page. Cards/rows open the peek on
 * click; the key is the direct route (and a middle/ctrl-click new tab, being a true
 * anchor) — stopPropagation keeps the surrounding row's peek handler out of it. */
export function ItemKeyLink({ itemKey, className }: { itemKey: string; className?: string }) {
  return (
    <Link
      to={RoutePath.issue}
      params={{ itemKey }}
      onClick={(event) => event.stopPropagation()}
      title={`Open ${itemKey}`}
      className={
        className ??
        "shrink-0 font-mono text-[11px] text-fg-muted hover:text-accent-text hover:underline"
      }
    >
      {itemKey}
    </Link>
  );
}

/** Personal-star indicator (spec 24) — shown when starred (non-interactive). */
export function StarBadge({ size = 12 }: { size?: number }) {
  return (
    <span title="Starred" className="shrink-0 text-amber-300">
      <Star size={size} fill="currentColor" aria-label="Starred" />
    </span>
  );
}

/**
 * Clickable personal star toggle, visible on touch and keyboard surfaces;
 * stops propagation so it doesn't open the item.
 */
export function StarButton({
  starred,
  onToggle,
  size = 13,
  disabled = false,
  itemKey,
  className = "",
}: {
  starred: boolean;
  onToggle: () => void;
  disabled?: boolean;
  itemKey?: string;
  size?: number;
  className?: string;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-busy={disabled}
      draggable={false}
      onPointerDown={event=>event.stopPropagation()}
      onDragStart={event=>{event.preventDefault();event.stopPropagation();}}
      onKeyDown={event=>{if(event.key === "Enter" || event.key === " ") event.stopPropagation();}}
      aria-pressed={starred}
      aria-label={`${starred ? "Unstar" : "Star"}${itemKey ? ` ${itemKey}` : ""}`}
      title={starred ? "Remove from Starred" : "Save to Starred"}
      onClick={(event: ReactMouseEvent) => {
        event.stopPropagation();
        onToggle();
      }}
      className={
        "shrink-0 cursor-pointer rounded p-1.5 focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-wait " +
        (starred
          ? "text-accent-text"
          : "text-fg-faint hover:text-accent-text ") +
        className
      }
    >
      <Star size={size} fill={starred ? "currentColor" : "none"} aria-hidden />
    </button>
  );
}

/** First-class flag indicator (spec 24) — shown when `item.flagged`. */
export function FlagBadge({ size = 12 }: { size?: number }) {
  return (
    <span title="Flagged" className="shrink-0 text-amber-400">
      <Flag size={size} fill="currentColor" aria-label="Flagged" />
    </span>
  );
}

/** Spec 121: a lock for restricted issues, a members glyph for internal ones —
 * shown on cards and rows only when the issue is NOT public. */
export function VisibilityBadge({
  visibility,
  size = 12,
}: {
  visibility: ItemVisibilityValue | undefined;
  size?: number;
}) {
  if (!visibility || visibility === ItemVisibility.public) return null;
  const meta = VISIBILITY_META[visibility];
  const Icon = meta.icon;
  return (
    <span title={`${meta.label} — ${meta.description}`} className="shrink-0 text-fg-muted">
      <Icon size={size} aria-label={meta.label} />
    </span>
  );
}

/** Spec 121: a project whose public issues the world can read. */
export function PublicProjectChip() {
  return (
    <span
      title="Public project — its public issues are readable without signing in"
      className="inline-flex items-center gap-1 rounded-md border border-subtle bg-surface px-1.5 py-0.5 text-[11px] text-fg-secondary"
    >
      <Globe size={11} aria-hidden />
      Public
    </span>
  );
}

/** Spec 121: the issue rail's visibility chip (label follows the project). */
export function VisibilityChip({
  visibility,
  isPublicProject,
  iconOnly = false,
}: {
  visibility: ItemVisibilityValue;
  isPublicProject: boolean;
  /** RADD-1287: beside a select that already names it, the chip is just the glyph
   *  (like the rail's state/priority chips) — not a second copy of the same word. */
  iconOnly?: boolean;
}) {
  const meta = VISIBILITY_META[visibility];
  const Icon = meta.icon;
  if (iconOnly) {
    return (
      <span title={meta.description} className="inline-flex size-5 items-center justify-center rounded-md border border-subtle bg-surface text-fg-secondary">
        <Icon size={12} aria-hidden />
      </span>
    );
  }
  return (
    <span
      title={meta.description}
      className="inline-flex items-center gap-1 rounded-md border border-subtle bg-surface px-1.5 py-0.5 text-xs text-fg-secondary"
    >
      <Icon size={12} aria-hidden />
      {isPublicProject ? meta.label : meta.privateLabel}
    </span>
  );
}

export function PriorityIcon({ priority, size = 14 }: { priority: PriorityValue; size?: number }) {
  const meta = PRIORITY_META[priority];
  const Icon = meta.icon;
  return <Icon size={size} className={meta.className} aria-label={`Priority: ${meta.label}`} />;
}

/**
 * Kind icon + optional label. `kind` may be undefined while the spec-02
 * backend hasn't landed — renders a neutral placeholder icon then.
 */
export function KindBadge({
  kind,
  withLabel = false,
  size = 14,
}: {
  kind: ItemKindValue | undefined;
  withLabel?: boolean;
  size?: number;
}) {
  const meta = kind ? KIND_META[kind] : undefined;
  const Icon = meta?.icon ?? NO_KIND_ICON;
  return (
    <span className="inline-flex items-center gap-1" title={meta ? meta.label : "Issue"}>
      <Icon size={size} className={meta?.className ?? "text-fg-muted"} aria-hidden />
      {withLabel && (
        <span className="text-xs text-fg-secondary">{meta ? meta.label : "Issue"}</span>
      )}
    </span>
  );
}

/** Issue-type chip (spec 51): the colored type chip, optionally with its name. */
export function TypeChip({ type, withLabel = false }: { type: TypeRef; withLabel?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1" title={`Type: ${type.name}`}>
      <ValueChip label={type.name} color={type.color} icon={type.icon} size={14} />
      {withLabel && <span className="text-xs text-fg-secondary">{type.name}</span>}
    </span>
  );
}

export function LabelChip({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-strong bg-elevated/60 px-1.5 py-px text-[11px] leading-4 text-fg">
      {name}
    </span>
  );
}

/**
 * Label chips capped at `max` — the rest collapse into a "+N" chip whose
 * tooltip lists them, so labels stop dominating rows and cards.
 */
export function LabelChips({
  labels,
  max,
  nowrap = false,
}: {
  labels: string[];
  max: number;
  /** Row surfaces: single line, clipped — chips must never wrap a row taller. */
  nowrap?: boolean;
}) {
  const shown = max > 0 ? labels.slice(0, max) : [];
  const hidden = labels.slice(shown.length);
  return (
    <span
      className={
        "flex min-w-0 items-center gap-1 " +
        (nowrap ? "flex-nowrap overflow-hidden" : "flex-wrap")
      }
    >
      {shown.map((label) => (
        <LabelChip key={label} name={label} />
      ))}
      {hidden.length > 0 && (
        <span
          title={hidden.join(", ")}
          className="inline-flex shrink-0 items-center rounded-full border border-strong bg-elevated/60 px-1.5 py-px text-[11px] leading-4 text-fg-muted"
        >
          +{hidden.length}
        </span>
      )}
    </span>
  );
}

/** State as a tinted pill (category color) — the far-right anchor of rows.
 * Fixed width (sized for "In Progress", the longest stock name) so a column of
 * pills keeps one edge and the chips before it never shift; longer custom
 * state names truncate with the full name in the tooltip. */
export function StatePill({ state }: { state: StateRef }) {
  const meta = CATEGORY_META[state.category];
  return (
    <span
      title={`State: ${state.name}`}
      className={`inline-flex w-[6.5rem] shrink-0 items-center justify-center gap-1.5 rounded border px-2 py-px text-[11px] leading-4 ${meta.pillClassName}`}
    >
      <span className={`size-1.5 shrink-0 rounded-full ${meta.dotClassName}`} aria-hidden />
      <span className="truncate">{state.name}</span>
    </span>
  );
}

/** Target-date chip; tinted red once overdue (pass `overdue` from the issue's state). */
export function DueBadge({ date, overdue }: { date: string; overdue: boolean }) {
  return (
    <span
      title={`Target date: ${date}`}
      className={
        "inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-px text-[11px] leading-4 " +
        (overdue ? "bg-red-500/10 text-red-300" : "bg-elevated text-fg-secondary")
      }
    >
      <CalendarClock size={11} aria-hidden />
      {shortDate(date)}
    </span>
  );
}

/** The shared Avatar at row/card sizing (size-5/6), with the assignee tooltip —
 * so custom avatar colors/emoji show on rows and cards too. */
export function AssigneeAvatar({ assignee, size = 5 }: { assignee: UserRef; size?: 5 | 6 }) {
  return (
    <Avatar user={assignee} size={size === 6 ? "sm" : "xs"} title={`Assignee: ${assignee.name}`} />
  );
}

/** Avatar-sized "—" for unassigned rows: keeps the column grid aligned where a
 * missing avatar would let everything after it drift left. */
export function UnassignedSlot({ size = 5 }: { size?: 5 | 6 }) {
  return (
    <span
      title="Unassigned"
      className={
        (size === 6 ? "size-6 text-[11px]" : "size-5 text-[10px]") +
        " inline-flex shrink-0 items-center justify-center rounded-full border border-dashed border-strong text-fg-faint"
      }
    >
      —
    </span>
  );
}

export function TeamBadge({ team }: { team: TeamRef }) {
  return (
    <span
      title={`Team: ${team.name}`}
      className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] leading-4 text-fg-secondary"
    >
      <Users size={11} aria-hidden />
      {team.name}
    </span>
  );
}

/** Epic-parent tag on cards/rows ("↳ TD-3"). */
export function ParentTag({ parent }: { parent: ItemParentRef }) {
  return (
    <span
      title={`Parent: ${parent.key} ${parent.title}`}
      className="inline-flex items-center gap-0.5 rounded bg-purple-500/15 px-1.5 py-px font-mono text-[11px] leading-4 text-purple-300"
    >
      <CornerDownRight size={11} aria-hidden />
      {parent.key}
    </span>
  );
}

/** Release chip ("v1.2") with a status dot — shown on cards and item detail (spec 18). */
export function ReleaseChip({ release }: { release: ReleaseRef }) {
  const meta = RELEASE_STATUS_META[release.status];
  return (
    <span
      title={`Release: ${release.version} (${meta.label})`}
      className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] leading-4 text-fg"
    >
      <Rocket size={11} aria-hidden />
      {release.version}
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} aria-hidden />
    </span>
  );
}

/** Cycle chip (sprint name) with a derived-status dot — shown on cards and detail (spec 18). */
export function CycleChip({ cycle }: { cycle: CycleRef }) {
  const meta = CYCLE_STATUS_META[cycle.status];
  return (
    <span
      title={`Cycle: ${cycle.name} (${meta.label})`}
      className="inline-flex items-center gap-1 rounded bg-elevated px-1.5 py-px text-[11px] leading-4 text-fg"
    >
      <RefreshCw size={10} aria-hidden />
      <span className="max-w-24 truncate">{cycle.name}</span>
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} aria-hidden />
    </span>
  );
}

/** Story points, one decimal at most ("3", "2.5") — shared by chips/headers (spec 70). */
export function formatPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1);
}

/** Story-points "Np" chip (spec 70) — rendered only on items that carry points. */
export function PointsChip({ points }: { points: number }) {
  return (
    <span
      title={`Story points: ${formatPoints(points)}`}
      className="inline-flex items-center rounded bg-teal-500/15 px-1.5 py-px text-[11px] leading-4 tabular-nums text-teal-300"
    >
      {formatPoints(points)}p
    </span>
  );
}

/** Epic progress ("3 children") shown on epic cards. */
export function ChildCount({ count }: { count: number }) {
  return (
    <span className="inline-flex items-center rounded bg-purple-500/15 px-1.5 py-px text-[11px] leading-4 text-purple-300">
      {count} {count === 1 ? "child" : "children"}
    </span>
  );
}
