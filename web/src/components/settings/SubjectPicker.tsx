import { useEffect, useId, useRef, useState } from "react";
import { Shield, User, Users, UsersRound, X } from "lucide-react";
import { GrantSubject, type GrantSubjectValue } from "../../lib/types";

export interface Subject {
  type: GrantSubjectValue;
  id: string;
  name: string;
}

export const SUBJECT_ICON = {
  [GrantSubject.role]: Shield,
  [GrantSubject.team]: Users,
  [GrantSubject.user]: User,
  [GrantSubject.group]: UsersRound,
} as const;

/**
 * Searchable role / team / user picker (spec 92) — the one control for choosing a
 * grant subject, used everywhere grants are edited. Shows a removable chip once
 * chosen; otherwise a combobox on TokenMultiSelect's mechanics (RADD-901): type
 * to filter, ↑/↓ move the highlight, Enter commits, Escape closes, rows are
 * real listbox options. The old list was `onMouseDown`-only — a keyboard user
 * could not grant access to anyone.
 */
export function SubjectPicker({
  subjects,
  value,
  onChange,
  placeholder = "Role, team, or user…",
}: {
  subjects: Subject[];
  value: Subject | null;
  onChange: (subject: Subject | null) => void;
  placeholder?: string;
}) {
  const listId = useId();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const term = filter.trim().toLowerCase();
  const matches = (term ? subjects.filter((s) => s.name.toLowerCase().includes(term)) : subjects).slice(
    0,
    12,
  );

  useEffect(() => setHighlight(0), [filter, open]);

  const commit = (subject: Subject) => {
    onChange(subject);
    setFilter("");
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setHighlight((h) => (matches.length ? (h + 1) % matches.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => (matches.length ? (h - 1 + matches.length) % matches.length : 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && matches[highlight]) commit(matches[highlight]);
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    }
  };

  if (value) {
    const Icon = SUBJECT_ICON[value.type];
    return (
      <button
        type="button"
        onClick={() => onChange(null)}
        aria-label={`Remove ${value.name}`}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-strong px-2 text-xs text-fg hover:border-emphasis cursor-pointer"
      >
        <Icon size={12} className="text-fg-muted" aria-hidden />
        {value.name}
        <X size={11} className="text-fg-muted" aria-hidden />
      </button>
    );
  }

  return (
    <div ref={ref} className="relative">
      <input
        value={filter}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && matches[highlight] ? `${listId}-${highlight}` : undefined}
        aria-label={placeholder}
        autoComplete="off"
        onChange={(e) => {
          setFilter(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        className="h-8 w-48 rounded-md border border-strong bg-surface px-2 text-xs text-heading placeholder:text-fg-faint"
      />
      {open && matches.length > 0 && (
        <ul
          id={listId}
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 max-h-56 w-56 overflow-y-auto rounded-md border border-strong bg-surface py-1 shadow-pop"
        >
          {matches.map((s, index) => {
            const Icon = SUBJECT_ICON[s.type];
            return (
              <li key={`${s.type}:${s.id}`}>
                <button
                  type="button"
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === highlight}
                  onMouseEnter={() => setHighlight(index)}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    commit(s);
                  }}
                  className={
                    "flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs cursor-pointer " +
                    (index === highlight ? "bg-elevated text-heading" : "text-fg hover:bg-elevated")
                  }
                >
                  <Icon size={12} className="text-fg-muted" aria-hidden />
                  <span className="truncate">{s.name}</span>
                  <span className="ml-auto text-[10px] uppercase text-fg-faint">{s.type}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
