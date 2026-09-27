/** Send email's recipient rule (RADD-1387), apart from its form so it is testable without a browser. */
import { NodeArity } from "@radd-plugin-ui/automations/types";
import { EmailRecipient } from "./types";

const ROLES: ReadonlySet<string> = new Set(Object.values(EmailRecipient));

/** Whether `to` names a role, resolved on one issue, rather than an address (the server's `is_role`). */
export const isRecipientRole = (to: unknown): boolean => ROLES.has(String(to ?? "").trim().toLowerCase());

/** `params` with arity per item when `to` is a role: at set arity a role resolves nobody, and the
 *  server refuses to store that pairing. */
export function withRecipientArity(params: Record<string, unknown>): Record<string, unknown> {
  return isRecipientRole(params.to) && params.arity !== NodeArity.item ? { ...params, arity: NodeArity.item } : params;
}
