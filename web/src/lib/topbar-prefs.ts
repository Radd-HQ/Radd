import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { ApiPath } from "./constants";
import { mePreferencesQuery, queryKeys } from "./queries";

/**
 * Per-user top-bar state, stored in the spec-94 server-side preferences dict
 * (`PUT /auth/me/preferences` shallow-merges by top-level key) so pins and
 * saved filters follow the user across browsers. Both hooks tolerate garbage
 * in the dict — malformed entries drop silently.
 */

/** Personal saved SLQ filters (global — they compose with any item view). */
export const SAVED_FILTERS_PREF_KEY = "slq.saved_filters";
/** Pinned favorite views, rendered as top-bar tabs. */
export const NAV_PINS_PREF_KEY = "nav.pins";

export interface SavedFilter {
  name: string;
  query: string;
}

function readSavedFilters(prefs: Record<string, unknown> | undefined): SavedFilter[] {
  const raw = prefs?.[SAVED_FILTERS_PREF_KEY];
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (entry): entry is SavedFilter =>
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as SavedFilter).name === "string" &&
      typeof (entry as SavedFilter).query === "string",
  );
}

/**
 * A pinned top-bar tab; `label` is the user's custom name for it.
 * Two kinds: a VIEW pin resolves live against the views list (renames follow
 * the view, deleted views self-heal away, same-name pins disambiguate with
 * the project key); a LINK pin is any other nav destination, captured as its
 * URL + the link text at pin time.
 */
export type NavPin =
  | { kind: "view"; id: string; label?: string }
  | { kind: "link"; path: string; title: string; label?: string };

/** A pin's identity — view id or URL path (uuids and paths never collide). */
export function pinKey(pin: NavPin): string {
  return pin.kind === "view" ? pin.id : pin.path;
}

function readPins(prefs: Record<string, unknown> | undefined): NavPin[] {
  const raw = prefs?.[NAV_PINS_PREF_KEY];
  if (!Array.isArray(raw)) return [];
  // Stored shapes, oldest first: plain view-id strings, {id, label} view
  // objects, {path, title, label} link objects. The kind is inferred from the
  // fields, so reads accept every generation forever.
  const pins: NavPin[] = [];
  for (const entry of raw) {
    if (typeof entry === "string") {
      pins.push({ kind: "view", id: entry });
      continue;
    }
    if (typeof entry !== "object" || entry === null) continue;
    const { id, path, title, label } = entry as Record<string, unknown>;
    const custom = typeof label === "string" && label !== "" ? { label } : {};
    if (typeof id === "string") pins.push({ kind: "view", id, ...custom });
    else if (typeof path === "string" && typeof title === "string")
      pins.push({ kind: "link", path, title, ...custom });
  }
  return pins;
}

function usePreferencesWrite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api.put<Record<string, unknown>>(ApiPath.mePreferences, patch),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.mePreferences, data),
  });
}

/** The user's saved filters + save/remove (upsert by name, case-sensitive). */
export function useSavedFilters(): {
  filters: SavedFilter[];
  save: (filter: SavedFilter) => void;
  remove: (name: string) => void;
} {
  const prefs = useQuery(mePreferencesQuery());
  const write = usePreferencesWrite();
  const filters = readSavedFilters(prefs.data);
  return {
    filters,
    save: (filter) =>
      write.mutate({
        [SAVED_FILTERS_PREF_KEY]: [
          ...filters.filter((entry) => entry.name !== filter.name),
          filter,
        ],
      }),
    remove: (name) =>
      write.mutate({
        [SAVED_FILTERS_PREF_KEY]: filters.filter((entry) => entry.name !== name),
      }),
  };
}

/** Pinned tabs + toggle/rename. Callers resolve view pins against the views
 * list and simply skip ids that no longer resolve (deleted/unshared views). */
export function useNavPins(): {
  pins: NavPin[];
  /** `key` is a pin identity: a view id or a link path (see pinKey). */
  isPinned: (key: string) => boolean;
  /** Pin when absent, unpin when present — matched by identity, not label. */
  toggle: (pin: NavPin) => void;
  /** Set a custom tab label; empty/whitespace clears back to the default. */
  rename: (key: string, label: string) => void;
} {
  const prefs = useQuery(mePreferencesQuery());
  const write = usePreferencesWrite();
  const pins = readPins(prefs.data);
  const writePins = (next: NavPin[]) => write.mutate({ [NAV_PINS_PREF_KEY]: next });
  return {
    pins,
    isPinned: (key) => pins.some((pin) => pinKey(pin) === key),
    toggle: (pin) =>
      writePins(
        pins.some((entry) => pinKey(entry) === pinKey(pin))
          ? pins.filter((entry) => pinKey(entry) !== pinKey(pin))
          : [...pins, pin],
      ),
    rename: (key, label) => {
      const trimmed = label.trim();
      writePins(
        pins.map((pin) => {
          if (pinKey(pin) !== key) return pin;
          const { label: _dropped, ...rest } = pin;
          return trimmed ? { ...rest, label: trimmed } : rest;
        }),
      );
    },
  };
}
