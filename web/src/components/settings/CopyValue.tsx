import { useState } from "react";
import { Check, Copy, Eye, EyeOff } from "lucide-react";
import { Button } from "../Button";

/** What a hidden secret renders as. A fixed width, so the mask says nothing
 * about the secret's length either. */
const MASK = "••••••••••••••••••••••••";

/** A labeled value with a copy button — secrets, URIs, anything the user's
 * next step is pasting somewhere else.
 *
 * `secret` (RADD-1227, GitHub #5): the value is HIDDEN by default and copy is
 * the primary action. Reveal is a deliberate, opt-in toggle; a failed copy
 * says so and points at Reveal rather than exposing the secret on its own.
 * `hint` is what the masked row shows instead of dots alone — a token's
 * prefix, say, so the person can match it to the list row later. A
 * non-secret value stays visible for manual selection. */
export function CopyValue({
  label,
  value,
  mono = false,
  secret = false,
  hint,
  size = "sm",
}: {
  label: string;
  value: string;
  mono?: boolean;
  secret?: boolean;
  /** Shown before the mask while hidden (e.g. a token prefix). */
  hint?: string;
  size?: "sm" | "md";
}) {
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [revealed, setRevealed] = useState(false);
  const hidden = secret && !revealed;
  const buttonSize = size === "sm" ? "sm" : undefined;
  const iconSize = size === "sm" ? 13 : 14;

  const copy = async () => {
    setCopyFailed(false);
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (permissions/insecure context). A visible value
      // stays selectable; a hidden one is NOT revealed on the person's behalf.
      setCopyFailed(true);
    }
  };

  return (
    <div className="flex flex-col gap-1" data-copy-value={secret ? (hidden ? "hidden" : "revealed") : "plain"}>
      <span className="text-xs font-medium text-fg-secondary">{label}</span>
      <div className="flex items-center gap-2">
        <code
          data-testid="copy-value"
          aria-label={hidden ? `${label} (hidden)` : undefined}
          className={`min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md border border-strong bg-base px-3 ${
            size === "sm" ? "py-1.5" : "py-2"
          } text-xs text-heading ${mono ? "font-mono" : ""} ${hidden ? "select-none text-fg-muted" : ""}`}
        >
          {hidden ? (
            <>
              {hint && <span className="text-fg-secondary">{hint}</span>}
              <span aria-hidden>{MASK}</span>
            </>
          ) : (
            value
          )}
        </code>
        {secret && (
          <Button
            variant="ghost"
            size={buttonSize}
            onClick={() => setRevealed((current) => !current)}
            aria-pressed={revealed}
            aria-label={revealed ? `Hide ${label}` : `Reveal ${label}`}
            title={revealed ? "Hide" : "Reveal — shows the secret on screen"}
          >
            {revealed ? <EyeOff size={iconSize} aria-hidden /> : <Eye size={iconSize} aria-hidden />}
            {revealed ? "Hide" : "Reveal"}
          </Button>
        )}
        <Button variant="ghost" size={buttonSize} onClick={() => void copy()} aria-label={`Copy ${label}`}>
          {copied ? (
            <>
              <Check size={iconSize} className="text-emerald-400" aria-hidden />
              Copied
            </>
          ) : (
            <>
              <Copy size={iconSize} aria-hidden />
              Copy
            </>
          )}
        </Button>
      </div>
      {copyFailed && (
        <p role="status" className="text-xs text-status-danger-ink">
          Couldn't copy to the clipboard.
          {hidden ? " Use Reveal to select it by hand." : " Select the value by hand."}
        </p>
      )}
    </div>
  );
}
