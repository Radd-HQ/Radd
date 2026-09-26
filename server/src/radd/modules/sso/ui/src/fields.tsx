import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button, copyText } from "@radd/plugin-sdk";

/** Labeled checkbox with an indented help line (the HostDialog idiom). */
export function CheckboxField({
  label,
  help,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  help?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="flex items-center gap-2 text-[13px] text-fg">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          className="size-3.5 accent-accent"
        />
        {label}
      </label>
      {help && <p className="mt-0.5 pl-[22px] text-xs text-fg-muted">{help}</p>}
    </div>
  );
}

/** The redirect URI to paste into the IdP's console — read-only, copyable. */
export function RedirectUriField({ uri }: { uri: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="mb-1 text-[13px] text-fg">Redirect URI</div>
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate rounded-md border border-subtle bg-base px-2 py-1.5 text-xs text-fg-secondary">
          {uri}
        </code>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            // "Copied" only when text was copied — plain-http installs have no Clipboard API.
            void copyText(uri).then((ok) => {
              if (!ok) return;
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <p className="mt-1 text-xs text-fg-muted">
        Add this as an authorized redirect URI in the provider&rsquo;s console. One URI serves
        every provider — the sign-in attempt carries which one it belongs to.
      </p>
    </div>
  );
}
