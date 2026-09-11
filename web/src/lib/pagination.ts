import { api } from "./api";

/** Complete a bounded relation list using the server's ordinary page contract. */
export async function allRelationRows<T>(path: string, query: Record<string, string>, signal: AbortSignal, limit = 200): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += limit) {
    signal.throwIfAborted();
    const page = await api.getPaged<T>(path, { signal, query: { ...query, limit: String(limit), offset: String(offset) } });
    result.push(...page.rows);
    if (page.rows.length < limit || (page.total !== null && result.length >= page.total)) return result;
  }
}
