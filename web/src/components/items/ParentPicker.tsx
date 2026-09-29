import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EyeOff, Pencil, X } from "lucide-react";
import { IconButton, useDebounced } from "@radd/plugin-sdk";
import { PARENT_SEARCH_LIMIT } from "../../lib/constants";
import { KIND_META } from "../../lib/meta";
import { linkSearchQuery } from "../../lib/queries";
import {
  ItemKind,
  type ItemKindValue,
  type ItemLinkSearchResult,
  type ItemParentRef,
} from "../../lib/types";

/** Typing settles for this long before the typeahead asks the server. */
const PARENT_SEARCH_DEBOUNCE_MS = 200;
/** A blur waits this long before closing the list, so a mousedown on a row lands first. */
const DROPDOWN_BLUR_CLOSE_MS = 120;

/** The kind a parent must have (spec-02 ladder): issue → epic, subtask → issue; an epic has none. */
export function requiredParentKind(kind: ItemKindValue): ItemKindValue | null {
  if (kind === ItemKind.issue) return ItemKind.epic;
  if (kind === ItemKind.subtask) return ItemKind.issue;
  return null;
}

/** What the parent row is CALLED for an item of `kind`: an issue has an "Epic", a subtask a
 *  "Parent issue" — the words the rail, the bulk bar and the proofs share (RADD-1471). */
export function parentLabel(kind: ItemKindValue): string {
  return kind === ItemKind.subtask ? "Parent issue" : "Epic";
}

interface ParentSearchInputProps {
  projectId: string;
  /** The kind every candidate must have — the server filters, so the limit buys pickable rows. */
  kind: ItemKindValue;
  /** Only candidates with no parent (an epic adopting existing issues, RADD-1473). */
  unparented?: boolean;
  /** Candidates to leave out — the item itself, or ones already picked. */
  excludeIds?: ReadonlySet<string>;
  id?: string;
  placeholder?: string;
  autoFocus?: boolean;
  onPick: (candidate: ItemLinkSearchResult) => void;
}

/**
 * Search-as-you-type over items of ONE kind, across every project the reader can see with this
 * project's own ranked first (the link-search seam, spec 80 — a parent may live in another
 * project). One component serves the create modal, the issue rail, the epic's "Add existing…"
 * and the bulk bar (RADD-1471), so a candidate row reads the same everywhere.
 */
export function ParentSearchInput({
  projectId,
  kind,
  unparented = false,
  excludeIds,
  id,
  placeholder,
  autoFocus = false,
  onPick,
}: ParentSearchInputProps) {
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState(false);
  const query = useDebounced(term.trim(), PARENT_SEARCH_DEBOUNCE_MS);
  // A subtask's parent issue lives in the subtask's own project (RADD-1492), so a
  // search for ISSUES stays home; a search for epics spans every readable project.
  const sameProject = kind === ItemKind.issue;
  const results = useQuery({
    ...linkSearchQuery(projectId, query, undefined, PARENT_SEARCH_LIMIT, { kind, unparented, sameProject }),
    enabled: open,
  });
  const candidates = useMemo(
    () =>
      (results.data ?? []).filter(
        (candidate) => candidate.kind === kind && !excludeIds?.has(candidate.id),
      ),
    [results.data, kind, excludeIds],
  );
  const kindWord = KIND_META[kind].label.toLowerCase();
  const listId = id ? `${id}-list` : undefined;
  return (
    <div className="relative">
      <input
        id={id}
        value={term}
        autoFocus={autoFocus}
        role="combobox"
        aria-expanded={open && candidates.length > 0}
        aria-controls={listId}
        aria-autocomplete="list"
        data-parent-search={kind}
        onChange={(event) => {
          setTerm(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        // A pick closes the list but keeps focus here, so a second pick (the multi-pick modal)
        // reopens it on click rather than waiting for a keystroke.
        onClick={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), DROPDOWN_BLUR_CLOSE_MS)}
        autoComplete="off"
        placeholder={placeholder ?? (sameProject ? `Search ${kindWord}s in this project…` : `Search ${kindWord}s across all projects…`)}
        className="h-8 w-full rounded-md border border-strong bg-surface px-2.5 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
      />
      {open && candidates.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-md border border-strong bg-surface py-1 shadow-pop"
        >
          {candidates.map((candidate) => (
            <li key={candidate.id} role="option" aria-selected={false}>
              <button
                type="button"
                data-parent-candidate={candidate.key}
                // onMouseDown fires before the input's onBlur, so the pick lands.
                onMouseDown={(event) => {
                  event.preventDefault();
                  onPick(candidate);
                  setTerm("");
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px] hover:bg-elevated cursor-pointer"
              >
                <span className="shrink-0 font-mono text-[11px] text-fg-muted">{candidate.key}</span>
                <span className="truncate text-fg">{candidate.title}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && query !== "" && results.isSuccess && candidates.length === 0 && (
        <p className="mt-1 text-[11px] text-fg-faint">No {kindWord} matches “{query}”.</p>
      )}
    </div>
  );
}

/** What the field holds: the current parent (`item.parent`) or a fresh pick — id, key and title. */
export type ParentPick = Pick<ItemParentRef, "id" | "key" | "title">;

interface ParentPickerFieldProps {
  label: string;
  projectId: string;
  /** The kind to SEARCH — the parent's kind, not the item's. */
  kind: ItemKindValue;
  value: ParentPick | null;
  /** A pick, or null for the clear action. */
  onChange: (next: ItemLinkSearchResult | null) => void;
  /** Off for a subtask: it cannot exist without a parent, it can only move to another one. */
  allowClear?: boolean;
  excludeIds?: ReadonlySet<string>;
  /** A line under the control — why there is no clear, for instance. */
  hint?: string;
  id?: string;
}

/**
 * A labelled parent field: the current parent as a chip with Change (and Clear when allowed), or
 * the search when there is none / a change is under way. The create modal holds the pick in state;
 * the rail PATCHes it (`ParentField` in PlanningFields).
 */
export function ParentPickerField({
  label,
  projectId,
  kind,
  value,
  onChange,
  allowClear = true,
  excludeIds,
  hint,
  id = "parent-search",
}: ParentPickerFieldProps) {
  const [editing, setEditing] = useState(false);
  const showChip = value !== null && !editing;
  const lower = label.toLowerCase();
  return (
    <div className="flex flex-col gap-1.5" data-parent-field={kind}>
      <label htmlFor={showChip ? undefined : id} className="text-xs font-medium text-fg-secondary">
        {label}
      </label>
      {showChip ? (
        <div
          className="flex h-8 items-center gap-2 rounded-md border border-strong bg-surface px-2.5 text-[13px]"
          data-parent-current={value.key}
        >
          <span className="shrink-0 font-mono text-[11px] text-fg-muted">{value.key}</span>
          <span className="min-w-0 flex-1 truncate text-fg" title={value.title}>
            {value.title}
          </span>
          <IconButton aria-label={`Change ${lower}`} onClick={() => setEditing(true)}>
            <Pencil size={13} aria-hidden />
          </IconButton>
          {allowClear && (
            <IconButton aria-label={`Clear ${lower}`} onClick={() => onChange(null)}>
              <X size={13} aria-hidden />
            </IconButton>
          )}
        </div>
      ) : (
        <div className="flex items-start gap-1">
          <div className="min-w-0 flex-1">
            <ParentSearchInput
              id={id}
              projectId={projectId}
              kind={kind}
              excludeIds={excludeIds}
              autoFocus={editing}
              onPick={(candidate) => {
                onChange(candidate);
                setEditing(false);
              }}
            />
          </div>
          {value !== null && (
            <IconButton aria-label={`Keep ${value.key}`} className="mt-1" onClick={() => setEditing(false)}>
              <X size={13} aria-hidden />
            </IconButton>
          )}
        </div>
      )}
      {hint && <p className="text-[11px] text-fg-muted">{hint}</p>}
    </div>
  );
}

/** The words for a parent the viewer may not read (RADD-1491), by the child's kind. */
export function hiddenParentText(kind: ItemKindValue): string {
  return kind === ItemKind.subtask ? "Under an issue you cannot see" : "In an epic you cannot see";
}

/**
 * The rail row for a parent that exists but was withheld (RADD-1491): the same label as the
 * picker, a muted line saying so, and NO picker — replacing what you cannot see is refused
 * server-side, and offering it would read as "this issue has no epic".
 */
export function HiddenParentField({ kind }: { kind: ItemKindValue }) {
  return (
    <div className="flex flex-col gap-1.5" data-parent-field={kind} data-parent-hidden>
      <span className="text-xs font-medium text-fg-secondary">{parentLabel(kind)}</span>
      <div className="flex h-8 items-center gap-2 rounded-md border border-subtle bg-surface px-2.5 text-[13px] text-fg-muted">
        <EyeOff size={13} aria-hidden />
        <span className="min-w-0 flex-1 truncate">{hiddenParentText(kind)}</span>
      </div>
      <p className="text-[11px] text-fg-muted">Someone with access to that project can change it.</p>
    </div>
  );
}
