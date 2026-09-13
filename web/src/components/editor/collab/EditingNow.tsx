import { Pencil } from "lucide-react";
import { Avatar, type AvatarUser } from "../../Avatar";
import { CollabRole, type Presence } from "./model";

/** How many faces before the row folds into "+N". */
const MAX_FACES = 5;

/**
 * Who is in the room (spec 122) — one compact row in the page header, shown in
 * read mode too. Faces come from the directory when it has the person (their
 * real avatar colour and emoji, as everywhere else); awareness carries only a
 * name for anyone the directory does not list. Editors wear a pencil badge;
 * the summary reads "2 editing · 1 viewing". Nothing renders while you are
 * alone: a strip that says "you" is noise.
 */
export function EditingNow({
  people,
  users,
  className = "",
}: {
  people: Presence[];
  /** The people directory, for real avatars. */
  users?: AvatarUser[];
  className?: string;
}) {
  const others = people.filter((person) => !person.self);
  if (others.length === 0) return null;
  const editing = people.filter((person) => person.role === CollabRole.editor).length;
  const viewing = people.length - editing;
  const shown = people.slice(0, MAX_FACES);
  const overflow = people.length - shown.length;
  const summary = [
    editing > 0 ? `${editing} editing` : null,
    viewing > 0 ? `${viewing} viewing` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div
      role="status"
      aria-label={`In this page: ${summary}`}
      data-editing-now
      className={`flex items-center gap-2 text-[11px] text-fg-muted ${className}`}
    >
      <span className="flex items-center -space-x-1.5">
        {shown.map((person) => {
          const known = users?.find((user) => user.id === person.user.id);
          const avatar: AvatarUser = known ?? { id: person.user.id, name: person.user.name };
          const label = `${person.user.name}${person.self ? " (you)" : ""} · ${
            person.role === CollabRole.editor ? "editing" : "viewing"
          }`;
          return (
            <span key={person.user.id} className="relative ring-2 ring-base rounded-full">
              <Avatar user={avatar} size="xs" title={label} />
              {person.role === CollabRole.editor && (
                <span
                  aria-hidden
                  className="absolute -bottom-0.5 -right-0.5 flex size-2.5 items-center justify-center rounded-full bg-accent text-white ring-1 ring-base"
                >
                  <Pencil size={6} strokeWidth={3} />
                </span>
              )}
            </span>
          );
        })}
        {overflow > 0 && (
          <span
            title={people
              .slice(MAX_FACES)
              .map((person) => person.user.name)
              .join(", ")}
            className="flex size-5 items-center justify-center rounded-full bg-elevated text-[9px] font-semibold text-fg-secondary ring-2 ring-base"
          >
            +{overflow}
          </span>
        )}
      </span>
      <span>{summary}</span>
    </div>
  );
}
