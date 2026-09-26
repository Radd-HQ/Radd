import { useSyncExternalStore } from "react";
import { Pencil } from "lucide-react";
import { Avatar, useContributedQuery, type AvatarUser } from "@radd/plugin-sdk";
import { CollabRole } from "./model";
import type { PresenceStore } from "./presence";

/** How many faces before the row folds into "+N". */
const MAX_FACES = 5;

/**
 * Who is in the room (spec 122) — one compact row in the page header, shown in
 * read mode too. Faces come from the directory auth contributes when it has
 * the person (their real avatar colour, emoji and picture, as everywhere
 * else); awareness carries only a name for anyone it does not list. Editors
 * wear a pencil badge; the summary reads "2 editing · 1 viewing". Nothing
 * renders while you are alone: a strip that says "you" is noise.
 */
export function EditingNow({ store }: { store: PresenceStore }) {
  const { people } = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const others = people.filter((person) => !person.self);
  const users = useContributedQuery<AvatarUser[]>("auth.people", {}, { enabled: others.length > 0 }).data;
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
      className="flex items-center gap-2 text-[11px] text-fg-muted"
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

/**
 * Beside the editor's Done: whether THIS client saves the shared copy, or who
 * does. `data-collab-saver` is the election as the proofs read it.
 */
export function SavingStatus({ store }: { store: PresenceStore }) {
  const { people, saver, self } = useSyncExternalStore(store.subscribe, store.getSnapshot);
  if (self === null) return null;
  const isSaver = saver === self;
  const saverName = people.find((person) => person.clientIds.includes(saver ?? -1))?.user.name;
  return (
    <span className="text-[11px] text-fg-muted" data-collab-saver={isSaver}>
      {isSaver || !saverName ? "Saving as you type" : `Saved by ${saverName}`}
    </span>
  );
}
