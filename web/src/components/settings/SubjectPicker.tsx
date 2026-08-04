import { useEffect, useRef, useState } from "react";
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
 * chosen; otherwise a filter input with a grouped, icon-tagged dropdown.
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
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
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

  if (value) {
    const Icon = SUBJECT_ICON[value.type];
    return (
      <button
        type="button"
        onClick={() => onChange(null)}
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-strong px-2 text-xs text-fg hover:border-emphasis cursor-pointer"
      >
        <Icon size={12} className="text-fg-muted" />
        {value.name}
        <X size={11} className="text-fg-muted" />
      </button>
    );
  }

  return (
    <div ref={ref} className="relative">
      <input
        value={filter}
        onChange={(e) => {
          setFilter(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className="h-8 w-48 rounded-md border border-strong bg-surface px-2 text-xs text-heading placeholder:text-fg-faint"
      />
      {open && matches.length > 0 && (
        <ul className="absolute left-0 top-full z-30 mt-1 max-h-56 w-56 overflow-y-auto rounded-md border border-strong bg-surface py-1 shadow-xl">
          {matches.map((s) => {
            const Icon = SUBJECT_ICON[s.type];
            return (
              <li key={`${s.type}:${s.id}`}>
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    onChange(s);
                    setFilter("");
                    setOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-elevated cursor-pointer"
                >
                  <Icon size={12} className="text-fg-muted" />
                  <span className="truncate text-fg">{s.name}</span>
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
