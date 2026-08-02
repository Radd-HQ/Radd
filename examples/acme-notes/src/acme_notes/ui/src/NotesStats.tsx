import { useQuery } from "@tanstack/react-query";
import { api, Card, Spinner, tokens } from "@radd/plugin-sdk";

/**
 * A widget fed by the plugin's OWN Python endpoint (`GET /api/v1/notes/stats`, see router.py +
 * service.py). This is the server-side-logic path: the aggregate (notes across the WHOLE project,
 * busiest issue) is computed in Python with a SQL query — the browser only ever holds one issue's
 * notes, so it couldn't compute this itself. The widget just fetches and renders.
 */
interface Stats {
  total: number;
  items_with_notes: number;
  top_item_id: string | null;
  top_item_count: number;
}

export function NotesStats() {
  const { data, isLoading } = useQuery({
    queryKey: ["acme-notes", "stats"],
    queryFn: () => api.get<Stats>("/notes/stats"),
  });

  return (
    <div data-plugin-widget="acme-notes-stats">
    <Card title="Server stats (computed in Python — GET /notes/stats)">
      {isLoading || !data ? (
        <Spinner />
      ) : (
        <div style={{ display: "flex", gap: 20, fontSize: 13, color: tokens.text }} data-stats-total={data.total}>
          <span>
            <strong style={{ color: tokens.heading }}>{data.total}</strong> notes
          </span>
          <span>
            across <strong style={{ color: tokens.heading }}>{data.items_with_notes}</strong> issues
          </span>
          {data.top_item_id && (
            <span>
              busiest issue: <strong style={{ color: tokens.heading }}>{data.top_item_count}</strong>{" "}
              notes
            </span>
          )}
        </div>
      )}
    </Card>
    </div>
  );
}
