import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, Button, Callout, CalloutKind, ErrorText, Modal, TextField } from "@radd/plugin-sdk";
import { MailPath } from "./api";
import type { MailSender, MailTestResult } from "./types";

/**
 * Send one real message and report what happened (RADD-955/958).
 *
 * The Message-ID shown is the one the RELAY reported using — the value
 * threading actually depends on, and not always the one Radd composed.
 */
export function TestDialog({ sender, onClose }: { sender: MailSender; onClose: () => void }) {
  const [to, setTo] = useState("");
  const send = useMutation({
    mutationFn: () =>
      api.post<MailTestResult>(MailPath.senderTest(sender.id), { to_address: to }),
  });

  return (
    <Modal title={`Send a test through ${sender.name}`} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField
          label="Send to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          placeholder="you@example.com"
        />
        {/* The house callouts, not the raw emerald/red tints this shipped with:
            their ink is tuned to their own fill in both themes (RADD-993). */}
        {send.data?.ok && (
          <Callout kind={CalloutKind.success}>
            Sent. The relay used Message-ID{" "}
            <code className="font-mono text-[11px]">{send.data.message_id}</code> — that is the
            value replies thread against.
          </Callout>
        )}
        {send.data && !send.data.ok && <Callout kind={CalloutKind.danger}>{send.data.error}</Callout>}
        {send.isError && <ErrorText error={send.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => send.mutate()} disabled={send.isPending || !to.includes("@")}>
            {send.isPending ? "Sending…" : "Send test"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
