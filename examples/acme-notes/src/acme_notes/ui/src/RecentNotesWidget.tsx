import { useQuery } from "@tanstack/react-query";
import { api, EmptyState, Spinner, tokens } from "@radd/plugin-sdk";

interface RecentNote {
  id: string;
  item_id: string | null;
  body: string;
  created_at: string | null;
}

/**
 * The "Most Recent Notes" dashboard widget TYPE (spec 94) — contributed to the `dashboard.widget`
 * slot. Fed by the plugin's own `GET /notes/recent` endpoint (server-ordered; the browser can't
 * cheaply get the newest notes across every issue). Drop it on any dashboard via Add widget.
 */
export function RecentNotesWidget() {
  const { data, isLoading } = useQuery({
    queryKey: ["acme-notes", "recent"],
    queryFn: () => api.get<RecentNote[]>("/notes/recent", { query: { limit: "10" } }),
  });

  return (
    <div data-plugin-widget="acme.recent-notes" style={{ padding: 4 }}>
      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
          <Spinner />
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState>No notes yet.</EmptyState>
      ) : (
        <ul style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {data.map((n) => (
            <li
              key={n.id}
              style={{
                fontSize: 13,
                color: tokens.text,
                borderBottom: `1px solid ${tokens.border}`,
                paddingBottom: 6,
              }}
            >
              <span style={{ marginRight: 6 }}>📝</span>
              {n.body}
              {n.created_at && (
                <span style={{ marginLeft: 6, fontSize: 11, color: tokens.textFaint }}>
                  {new Date(n.created_at).toLocaleDateString()}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
