import { useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";
import { Entity, entityMeta } from "../../lib/cache";
import { ProjectSelect } from "../projects/ProjectSelect";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";
import { shiftIsoDay } from "../../lib/dates";

interface ActivityPage { entries: { id: number; at: string; action: string; item_key: string; comment_id: string | null }[]; next: number | null }
export function ActivityWidget({ config = {} }: { config?: { project_id?: string | null; start?: string; end?: string } }) {
  const [project, setProject] = useState(config.project_id ?? "");
  const [start, setStart] = useState(config.start ?? "");
  const [end, setEnd] = useState(config.end ?? "");
  const query = useInfiniteQuery({ queryKey: ["my-activity", project, start, end], meta: entityMeta(Entity.item, Entity.comment, Entity.worklog), initialPageParam: null as number | null,
    queryFn: ({ signal, pageParam }) => api.get<ActivityPage>("/dashboards/my-work/activity", { signal, query: { project_id: project || undefined, start: start ? `${start}T00:00:00Z` : undefined, end: end ? `${shiftIsoDay(end, 1)}T00:00:00Z` : undefined, before: pageParam ? String(pageParam) : undefined } }),
    getNextPageParam: page => page.next ?? undefined });
  let day = "";
  return <div className="space-y-2">
    <ProjectSelect label="Project" value={project} onChange={setProject} emptyLabel="All projects" emptyValue="" />
    <div className="flex flex-wrap gap-2 text-xs"><label>From <input aria-label="Activity from" type="date" value={start} onChange={e => setStart(e.target.value)} className="bg-base" /></label><label>To <input aria-label="Activity to" type="date" value={end} min={start} onChange={e => setEnd(e.target.value)} className="bg-base" /></label></div>
    {query.isPending && <p className="text-sm text-fg-muted">Loading activity…</p>}
    {query.isError && <ErrorText error={query.error} />}
    {query.data?.pages.flatMap(page => page.entries).map(entry => {
      const date = new Date(entry.at).toLocaleDateString(); const heading = date !== day; day = date;
      return <div key={entry.id}>{heading && <h3 className="mt-3 text-xs font-medium text-fg-muted">{date}</h3>}
        <a href={`/issues/${entry.item_key}${entry.comment_id ? `?comment=${entry.comment_id}` : ""}`} className="flex gap-2 border-b border-subtle py-2 text-sm hover:bg-elevated">
          <span>{entry.action} <span className="text-accent-text">{entry.item_key}</span></span><time className="ml-auto text-xs text-fg-muted">{new Date(entry.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
        </a></div>;
    })}
    {query.data?.pages.every(page => !page.entries.length) && !query.hasNextPage && <p className="text-sm text-fg-muted">No activity in this range.</p>}
    {(query.hasNextPage || query.isError) && <Button size="sm" disabled={query.isFetching} onClick={() => query.isError ? void query.refetch() : void query.fetchNextPage()}>{query.isError ? "Retry" : "Show more"}</Button>}
  </div>;
}
