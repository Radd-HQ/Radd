import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "../Button";

/** A labeled value with a copy button — secrets, URIs, anything the user's
 * next step is pasting somewhere else. Stays visible for manual selection
 * when the clipboard is unavailable. */
export function CopyValue({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable — the value stays selectable.
    }
  };
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-fg-secondary">{label}</span>
      <div className="flex items-center gap-2">
        <code
          className={`min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md border border-strong bg-base px-3 py-1.5 text-xs text-heading ${
            mono ? "font-mono" : ""
          }`}
        >
          {value}
        </code>
        <Button variant="ghost" size="sm" onClick={() => void copy()}>
          {copied ? (
            <>
              <Check size={13} className="text-emerald-400" aria-hidden />
              Copied
            </>
          ) : (
            <>
              <Copy size={13} aria-hidden />
              Copy
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
