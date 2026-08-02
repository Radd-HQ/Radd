/** Recently-viewed issue trail (spec 37) — per-browser localStorage, newest first. */

const STORAGE_KEY = "radd.recent-items";
const MAX_ENTRIES = 12;

export interface RecentItem {
  key: string;
  title: string;
  at: number;
}

export function listRecentItems(): RecentItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as RecentItem[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function recordRecentItem(key: string, title: string): void {
  try {
    const rest = listRecentItems().filter((entry) => entry.key !== key);
    const next = [{ key, title, at: Date.now() }, ...rest].slice(0, MAX_ENTRIES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage unavailable (private mode/quota) — the trail is best-effort.
  }
}

/** Drop one key from the trail (deleted items, dead links). */
export function removeRecentItem(key: string): void {
  try {
    const next = listRecentItems().filter((entry) => entry.key !== key);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // best-effort
  }
}
