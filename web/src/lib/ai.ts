import { ApiError, errorMessage } from "./api";

/**
 * Shared presentation helpers for the AI affordances (spec 46). The module's
 * error contract: 502 = provider/network failure (clean message), 404 = AI is
 * disabled (module dormant) — affordances hide rather than show a dead error.
 */

export const AI_PROVIDER_UNAVAILABLE_MESSAGE = "AI provider unavailable.";

/** True when an AI call 404'd — the module got disabled (possibly mid-session). */
export function isAiGone(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/** Inline error text for an AI call: 502 → the provider message, else as-is. */
export function aiErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status === 502) return AI_PROVIDER_UNAVAILABLE_MESSAGE;
  return errorMessage(error);
}
