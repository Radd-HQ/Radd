import { ApiError, errorMessage } from "./api";
export interface PositionedError {
  message: string;
  /** Character offset into the query, or null when the backend gave none. */
  position: number | null;
}

/** Extract a positioned API error from a thrown value; null for anything else. */
export function positionedErrorOf(error: unknown): PositionedError | null {
  if (!(error instanceof ApiError) || error.status !== 422) return null;
  const { detail } = error;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const payload = detail as { detail?: unknown; position?: unknown };
    if (typeof payload.detail === "string") {
      return {
        message: payload.detail,
        position: typeof payload.position === "number" ? payload.position : null,
      };
    }
  }
  return { message: errorMessage(error), position: null };
}
