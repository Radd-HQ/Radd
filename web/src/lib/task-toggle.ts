import { api, errorMessage } from "./api";
import { pushToast } from "./toast";

/**
 * RADD-1296: send one checklist tick to a surface's `…/tasks` endpoint.
 *
 * `expectedBody` is the text the reader was looking at — the server refuses
 * (409) when the stored text has changed since, rather than flipping a box in
 * a document the reader never saw. A refusal is a toast, and the caller's
 * caches refresh either way so the viewer shows what is actually stored.
 */
export async function sendTaskToggle<T>(
  path: string,
  toggle: { index: number; checked: boolean },
  expectedBody: string,
): Promise<T | null> {
  try {
    return await api.post<T>(path, { ...toggle, expected_body: expectedBody });
  } catch (error) {
    pushToast(errorMessage(error));
    return null;
  }
}
