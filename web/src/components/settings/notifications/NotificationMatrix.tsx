import { Fragment } from "react";
import { RuleScope, type ChannelValue, type NotificationPrefs, type NotificationTypeValue, type RuleScopeValue } from "../../../lib/types";
import { ChannelCell } from "./ChannelCell";
import { PERSONAL_ONLY_REASON, SCOPE_HINTS, SCOPE_LABELS, resolveCell } from "./matrix";

/**
 * The defaults matrix: one row per notification kind, one column per
 * relationship.
 *
 * Rows come from the SERVER's vocabulary (`prefs.kinds`), not a table in this
 * file. The panel this replaces held its own `Record<NotificationType, string>`,
 * so a kind added on the server had no row here and nothing failed — it simply
 * could not be configured, which is the quietest kind of broken.
 *
 * A PERSONAL kind's other two columns are greyed rather than hidden. Hiding them
 * would leave a ragged grid and no explanation; the disabled cell says why on
 * hover, which is the spec-96 posture applied to a preference rather than a
 * field.
 */
export function NotificationMatrix({
  prefs,
  disabled,
  onCell,
}: {
  prefs: NotificationPrefs;
  disabled: boolean;
  onCell: (
    scope: RuleScopeValue,
    kind: NotificationTypeValue,
    channel: ChannelValue | null,
  ) => void;
}) {
  return (
    <>
      {/* The column hints used to live only in `title=` tooltips — invisible on
          touch, undiscoverable everywhere else, and the one thing a first-time
          visitor actually needs. A three-line legend costs almost nothing. */}
      <div className="mb-3 flex flex-col gap-1" data-matrix-legend>
        {prefs.scopes.map((scope) => (
          <p key={scope} className="text-[12px] leading-snug text-fg-muted">
            <span className="font-medium text-fg-secondary">{SCOPE_LABELS[scope]}</span>
            {" — "}
            {SCOPE_HINTS[scope]}
          </p>
        ))}
      </div>
      <div
      // `inline-grid` and a BOUNDED label column, not `1fr`. Stretched across a
      // 48rem settings column, the labels sat 700px from their own cells and the
      // row stopped being a row — you were reading a name on the left and
      // guessing which line of marks on the right belonged to it. A matrix is
      // only a matrix while the eye can travel across one.
      className="inline-grid items-center gap-x-3 gap-y-1"
      style={{
        gridTemplateColumns: `minmax(0,15rem) repeat(${prefs.scopes.length}, minmax(4.5rem, auto))`,
      }}
      data-notification-matrix
    >
      <span />
      {prefs.scopes.map((scope) => (
        <span
          key={scope}
          title={SCOPE_HINTS[scope]}
          className="justify-self-center px-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-muted"
        >
          {SCOPE_LABELS[scope]}
        </span>
      ))}
      {prefs.kinds.map((kind) => (
        <Fragment key={kind.kind}>
          <span className="flex min-w-0 flex-col py-0.5">
            <span className="text-[13px] text-fg">{kind.label}</span>
            <span className="text-[11px] leading-snug text-fg-muted">{kind.description}</span>
          </span>
          {prefs.scopes.map((scope) => {
            const personalElsewhere = kind.personal && scope !== RuleScope.own;
            const cell = resolveCell(prefs, scope, kind.kind);
            return (
              <span key={scope} className="w-full">
                <ChannelCell
                  fill
                  label={`${kind.label} — ${SCOPE_LABELS[scope]}`}
                  resolved={cell.channel}
                  inheritedFrom={cell.inheritedFrom}
                  disabled={disabled || personalElsewhere}
                  disabledReason={personalElsewhere ? PERSONAL_ONLY_REASON : undefined}
                  onChange={(channel) => onCell(scope, kind.kind, channel)}
                />
              </span>
            );
          })}
        </Fragment>
      ))}
      </div>
    </>
  );
}
