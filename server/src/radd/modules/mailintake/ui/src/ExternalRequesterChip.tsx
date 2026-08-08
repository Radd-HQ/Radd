import { useQuery } from "@tanstack/react-query";
import { api, tokens } from "@radd/plugin-sdk";
import { Mail, Star } from "lucide-react";

/**
 * External requesters (spec 62) as a FEDERATED remote (spec 94): rendered only when the item has at
 * least one mail contact — raised by email or a public form by someone without an account. Agents'
 * PUBLIC comments go back out to every address listed here.
 *
 * RADD-980 made the list n-ary. It used to read the singular `/mail-contact` and render one chip,
 * which was accurate while a ticket could only ever have one contact; now a customer's CC'd
 * colleague is a contact too, and the rail has to say so — a reply fans out to all of them, and a
 * screen that shows one address makes that fan-out invisible. The PRIMARY (the person who raised
 * the ticket) is first and starred, which is the row every singular seam still means: CSAT, the
 * automation `contact` recipient role, the singular endpoint.
 *
 * Styled from `@radd/plugin-sdk` tokens — no hardcoded color, so it tracks the host theme.
 */

interface MailContact {
  email: string;
  name: string;
  is_primary: boolean;
}

const mailContactsKey = (itemId: string) => ["radd-remote", "mailintake", itemId] as const;

export function ExternalRequesterChip({ itemId }: { itemId: string }) {
  // GET /items/{id}/mail-contacts — a collection, so "none" is [] and needs no error branch.
  const { data: contacts } = useQuery({
    queryKey: mailContactsKey(itemId),
    queryFn: () => api.get<MailContact[]>(`/items/${itemId}/mail-contacts`),
    retry: false,
  });
  if (!contacts?.length) return null; // most items have none

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
        {contacts.length > 1 ? "External requesters" : "External requester"}
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {contacts.map((contact) => (
          <span
            key={contact.email}
            title={
              contact.is_primary
                ? `${contact.name || contact.email} — raised this request`
                : contact.name || contact.email
            }
            style={chip}
          >
            {contact.is_primary ? (
              <Star size={12} aria-hidden style={{ flexShrink: 0 }} />
            ) : (
              <Mail size={12} aria-hidden style={{ flexShrink: 0 }} />
            )}
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {contact.email}
            </span>
          </span>
        ))}
      </div>
      <p style={{ marginTop: 4, fontSize: 11, color: tokens.textFaint }}>
        Public comments are emailed back
      </p>
    </div>
  );
}
