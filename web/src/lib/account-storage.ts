/** Content-bearing browser state belongs to the resolved account. */
let accountId: string | null = null;

export function setStorageAccount(id: string | null) {
  accountId = id;
  // Old unscoped titles cannot safely be assigned to any account.
  try { localStorage.removeItem("radd.recent-items"); } catch { /* unavailable */ }
}

export function accountStorageKey(key: string): string {
  return `${key}:account:${accountId ?? "signed-out"}`;
}
