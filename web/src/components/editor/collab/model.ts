/**
 * The pure half of collaborative editing (spec 122): the awareness vocabulary,
 * the saver election and the presence model. No imports on purpose — this
 * file is what `web/scripts/collab-election.test.mjs` loads under node, and it
 * is the whole contract between clients: two tabs that disagree about who
 * saves would write the same page twice, or never.
 */

/** What a client is in the room. The server drops an observer's document
 *  updates; only its awareness (presence) is relayed. */
export const CollabRole = {
  editor: "editor",
  observer: "observer",
} as const;
export type CollabRoleValue = (typeof CollabRole)[keyof typeof CollabRole];

/** The person behind a client, as awareness carries it to everyone else.
 *  `color` is the remote-cursor colour (see presence-color.ts). */
export interface CollabUser {
  id: string;
  name: string;
  color: string;
  emoji: string | null;
}

/** The awareness state every client publishes. y-prosemirror adds `cursor`. */
export interface CollabAwarenessState {
  user: CollabUser;
  role: CollabRoleValue;
}

/** One person in the room — several tabs of the same account fold into one
 *  entry, editing if ANY of them is. */
export interface Presence {
  user: CollabUser;
  role: CollabRoleValue;
  clientIds: number[];
  /** This tab's own account. */
  self: boolean;
}

export interface PresenceSnapshot {
  /** In order of arrival (lowest client id first). */
  people: Presence[];
  /** The elected saver's client id, or null when no editor is connected. */
  saver: number | null;
}

export const EMPTY_PRESENCE: PresenceSnapshot = { people: [], saver: null };

/** Whatever a peer published — an older client may carry no role at all. */
type LooseState = { [field: string]: unknown } | null | undefined;

function isEditor(state: LooseState): boolean {
  return state?.role === CollabRole.editor;
}

function userOf(state: LooseState): CollabUser | null {
  const user = state?.user;
  if (!user || typeof user !== "object") return null;
  const { id, name, color, emoji } = user as Partial<CollabUser>;
  if (typeof id !== "string" || typeof name !== "string") return null;
  return {
    id,
    name,
    color: typeof color === "string" ? color : "",
    emoji: typeof emoji === "string" ? emoji : null,
  };
}

/**
 * Who saves: the connected EDITOR with the lowest awareness client id.
 *
 * Deterministic from the shared awareness map alone, so every client elects
 * the same saver without a round trip, and a departure re-elects by the same
 * rule. Observers never save — the server would not accept their writes as
 * the room's anyway. Returns null when nobody is editing.
 */
export function electSaver(states: Iterable<[number, LooseState]>): number | null {
  let saver: number | null = null;
  for (const [clientId, state] of states) {
    if (!isEditor(state)) continue;
    if (saver === null || clientId < saver) saver = clientId;
  }
  return saver;
}

/** The awareness map folded into people, plus the election. */
export function presenceSnapshot(
  states: Iterable<[number, LooseState]>,
  selfUserId: string | null,
): PresenceSnapshot {
  const byUser = new Map<string, Presence>();
  const entries = [...states].sort(([a], [b]) => a - b);
  for (const [clientId, state] of entries) {
    const user = userOf(state);
    if (!user) continue;
    const role = isEditor(state) ? CollabRole.editor : CollabRole.observer;
    const existing = byUser.get(user.id);
    if (existing) {
      existing.clientIds.push(clientId);
      if (role === CollabRole.editor) existing.role = role;
      continue;
    }
    byUser.set(user.id, { user, role, clientIds: [clientId], self: user.id === selfUserId });
  }
  return { people: [...byUser.values()], saver: electSaver(entries) };
}
