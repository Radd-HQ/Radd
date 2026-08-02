import { useQuery } from "@tanstack/react-query";
import { api, ApiError, tokens } from "@radd/plugin-sdk";
import { Star } from "lucide-react";

/**
 * CSAT rating chip (spec 65) as a FEDERATED remote (spec 94): rendered only once the requester
 * ANSWERED the resolution survey — `GET /items/{id}/csat` is 404-quiet until then. Stars + the
 * free-text comment as the tooltip. Extracted from the host's IssueProperties into the `csat`
 * plugin's own UI bundle; styled from `@radd/plugin-sdk` tokens — no hardcoded color, tracks theme.
 */

interface ItemCsat {
  rating: number;
  comment: string;
  responded_at: string;
}

const RATING_STARS = [1, 2, 3, 4, 5];

const itemCsatKey = (itemId: string) => ["radd-remote", "csat", itemId] as const;

export function CsatChip({ itemId }: { itemId: string }) {
  // GET /items/{id}/csat — 404-quiet: server 404s both "never surveyed" and "not answered yet".
  const { data: csat } = useQuery({
    queryKey: itemCsatKey(itemId),
    queryFn: async (): Promise<ItemCsat | null> => {
      try {
        return await api.get<ItemCsat>(`/items/${itemId}/csat`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false,
  });
  if (!csat) return null; // no survey, or not answered yet

  const badge: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 2,
    borderRadius: tokens.radius,
    border: `1px solid ${tokens.warning}`,
    background: tokens.panel,
    padding: "4px 8px",
  };

  return (
    <div style={{ padding: "12px 16px" }} data-plugin-section="csat">
      <p style={{ marginBottom: 6, fontSize: 12, fontWeight: 500, color: tokens.textMuted }}>
        Requester satisfaction
      </p>
      <span title={csat.comment || `Rated ${csat.rating} of 5`} style={badge}>
        {RATING_STARS.map((star) => {
          const filled = star <= csat.rating;
          return (
            <Star
              key={star}
              size={13}
              aria-hidden
              color={filled ? tokens.warning : tokens.textFaint}
              fill={filled ? tokens.warning : "none"}
            />
          );
        })}
        <span style={{ marginLeft: 6, fontSize: 12, color: tokens.warning }}>
          {csat.rating}/5
        </span>
      </span>
      {csat.comment && (
        <p
          title={csat.comment}
          style={{
            marginTop: 4,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            fontSize: 11,
            color: tokens.textFaint,
          }}
        >
          “{csat.comment}”
        </p>
      )}
    </div>
  );
}
