/**
 * The transition-rule editor slot (RADD-1383). The transitions editor edits the checks workflow
 * evaluates itself; a plugin serving another check on the kernel TRANSITION_CHECK socket contributes
 * that check's editor here, with `match` set to its check key (approvals: `require_approval`). The
 * host renders every contribution on every transition row and keeps contributed rules AFTER its own,
 * so a gate someone else clears still reads last.
 */
export const TRANSITION_RULE_SLOT = "workflow.transition.rule";

/** One stored rule, as `GET /projects/{id}/transitions` carries it. */
export interface ContributedTransitionRule {
  check: string;
  params: Record<string, unknown>;
}

export interface TransitionRuleEditorProps {
  /** Every rule on the row — an editor finds its own by `check`. */
  rules: ContributedTransitionRule[];
  /** Write one check's rule: `params` replaces it (or adds it), `null` removes it. Every other rule
   *  on the row is kept as it is. */
  onChange: (check: string, params: Record<string, unknown> | null) => void;
  canManage: boolean;
  /** A save is in flight: controls stay disabled until the server's answer lands. (Not `pending`:
   *  that name is `<Slot>`'s own prop, which it keeps rather than forwards.) */
  saving: boolean;
}
