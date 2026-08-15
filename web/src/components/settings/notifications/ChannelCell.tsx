import { Bell, Mail, Minus } from "lucide-react";
import { DropdownMenu } from "../../DropdownMenu";
import { Channel, type ChannelValue } from "../../../lib/types";

/**
 * One cell of the notification matrix: four states plus "inherit".
 *
 * **Why a menu and not two checkboxes.** Two boxes can say off / inbox / email /
 * both — but they cannot say UNSET, and unset is most of this grid. Every cell a
 * person has not touched resolves to something, from somewhere, and a control
 * that renders inheritance as "unchecked" is a control that lies about the two
 * cases a notification preference exists to distinguish: "I turned this off" and
 * "I never said". So the trigger shows what the cell RESOLVES to, dimmed when
 * that answer was inherited, and names the source in its tooltip.
 *
 * The trigger is two channel pills rather than a word, because the reader's
 * question is "does this reach my inbox / my mailbox", and two lit-or-unlit
 * icons answer it at a glance across thirteen rows in a way "Both" does not.
 *
 * `data-channel` and `data-inherited` are on the trigger for the CDP proof:
 * "the cell says email-only" is a computed-style question otherwise, and a proof
 * that reads colours would break on a palette change rather than a bug.
 */
export interface ChannelCellProps {
  /** What this cell resolves to right now — the saved value or the inherited one. */
  resolved: ChannelValue;
  /** Null when the person has set this cell explicitly. */
  inheritedFrom: string | null;
  label: string;
  disabled?: boolean;
  /** Why it is disabled — shown on hover, the spec-96 posture. */
  disabledReason?: string;
  /**
   * Fill the grid column (the matrix) rather than shrink to the icons (the
   * inline subscription rows).
   *
   * Not cosmetic. A disabled cell renders ONE mark and a live one renders two,
   * so a shrink-to-fit control centres the two at different x — and a matrix
   * whose columns wobble by ten pixels between rows has stopped reading as a
   * grid. The CDP proof measured exactly that and failed; filling the column
   * makes every cell start at the column's x by construction, with no width
   * constant to keep in step.
   */
  fill?: boolean;
  onChange: (channel: ChannelValue | null) => void;
}

const CHANNEL_LABELS: Record<ChannelValue, string> = {
  [Channel.off]: "Off",
  [Channel.inbox]: "Inbox only",
  [Channel.email]: "Email only",
  [Channel.both]: "Inbox and email",
};


export function ChannelCell({
  resolved,
  inheritedFrom,
  label,
  disabled = false,
  disabledReason,
  fill = false,
  onChange,
}: ChannelCellProps) {
  const box = fill ? "w-full " : "";
  const inInbox = resolved === Channel.inbox || resolved === Channel.both;
  const byEmail = resolved === Channel.email || resolved === Channel.both;
  const inherited = inheritedFrom !== null;
  const title = disabled
    ? disabledReason
    : inherited
      ? `${CHANNEL_LABELS[resolved]} — inherited from ${inheritedFrom}`
      : CHANNEL_LABELS[resolved];

  if (disabled) {
    return (
      <span
        className={box + "flex items-center justify-center gap-1 rounded-md px-1.5 py-1 opacity-40"}
        title={title}
        data-channel="disabled"
        aria-label={`${label} — not applicable`}
      >
        <Minus size={13} className="text-fg-faint" aria-hidden />
      </span>
    );
  }

  return (
    <DropdownMenu
      label={`${label} — ${CHANNEL_LABELS[resolved]}`}
      align="end"
      widthClass="w-44"
      className={fill ? "w-full" : ""}
      items={[
        {
          kind: "action",
          label: "Inherit",
          onSelect: () => onChange(null),
          disabled: inherited,
        },
        { kind: "separator" },
        ...([Channel.off, Channel.inbox, Channel.email, Channel.both] as const).map(
          (option) => ({
            kind: "action" as const,
            label: CHANNEL_LABELS[option],
            onSelect: () => onChange(option),
          }),
        ),
      ]}
      trigger={({ ref, open, toggle }) => (
        <button
          ref={ref}
          type="button"
          onClick={toggle}
          aria-label={`${label} — ${CHANNEL_LABELS[resolved]}`}
          aria-haspopup="menu"
          aria-expanded={open}
          title={title}
          data-channel={resolved}
          data-inherited={inherited ? "true" : "false"}
          className={
            box +
            "flex items-center justify-center gap-1 rounded-md border px-1.5 py-1 cursor-pointer " +
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus " +
            (open
              ? "border-emphasis bg-elevated "
              : "border-transparent hover:border-strong hover:bg-elevated ") +
            // Dim states the INHERITANCE, not the value: an inherited "both" is
            // still both. Opacity is safe here because the marks are icons, not
            // text — the 4.5:1 rule that killed dimming elsewhere is about
            // readable characters.
            (inherited ? "opacity-55" : "")
          }
        >
          <Bell
            size={13}
            aria-hidden
            className={inInbox ? "text-accent-text-strong" : "text-fg-faint"}
            strokeWidth={inInbox ? 2.4 : 1.6}
          />
          <Mail
            size={13}
            aria-hidden
            className={byEmail ? "text-accent-text-strong" : "text-fg-faint"}
            strokeWidth={byEmail ? 2.4 : 1.6}
          />
        </button>
      )}
    />
  );
}
