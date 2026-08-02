import { useQuery } from "@tanstack/react-query";
import { api, ApiError, tokens } from "@radd/plugin-sdk";
import { Mail } from "lucide-react";

/**
 * External requester (spec 62) as a FEDERATED remote (spec 94): rendered only when the item has a
 * mail contact — raised by email or a public form by someone without an account. The chip shows the
 * address; agents' PUBLIC comments go back out to it by email. Extracted from the host's
 * IssueProperties into the `mailintake` plugin's own UI bundle. Styled from `@radd/plugin-sdk`
 * tokens — no hardcoded color, so it tracks the host theme.
 */

interface MailContact {
  email: string;
  name: string;
}

const mailContactKey = (itemId: string) => ["radd-remote", "mailintake", itemId] as const;

export function ExternalRequesterChip({ itemId }: { itemId: string }) {
  // GET /items/{id}/mail-contact — 404-quiet: most items have none, so "no contact" is null.
  const { data: contact } = useQuery({
    queryKey: mailContactKey(itemId),
    queryFn: async (): Promise<MailContact | null> => {
      try {
        return await api.get<MailContact>(`/items/${itemId}/mail-contact`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
  if (!contact) return null; // most items have no contact

  const chip: React.CSSProperties = {
    display: "inline-flex",
    maxWidth: "100%",
    alignItems: "center",
    gap: 6,
    borderRadius: tokens.radius,
    border: `1px solid ${tokens.accent}`,
    background: tokens.panel,
    padding: "4px 8px",
    fontSize: 12,
    color: tokens.accent,
  };

  return (
    <div style={{ padding: "12px 16px" }} data-plugin-section="mailintake">
      <p style={{ marginBottom: 6, fontSize: 12, fontWeight: 500, color: tokens.textMuted }}>
        External requester
      </p>
      <span title={contact.name || contact.email} style={chip}>
        <Mail size={12} aria-hidden style={{ flexShrink: 0 }} />
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {contact.email}
        </span>
      </span>
      <p style={{ marginTop: 4, fontSize: 11, color: tokens.textFaint }}>
        Public comments are emailed back
      </p>
    </div>
  );
}
