import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Star, List, LayoutGrid } from "lucide-react";
import { api, errorMessage, type CursorPage } from "../lib/api";
import { Entity, entityMeta } from "../lib/cache";
import { accountStorageKey } from "../lib/account-storage";
import { RoutePath } from "../lib/constants";
import { useDebounced, useOpenIssueRef } from "../lib/hooks";
import { itemsCountQuery } from "../lib/queries";
import type { Item } from "../lib/types";
import { QuickStar } from "../components/items/QuickStar";
import { Avatar } from "../components/Avatar";
import { PRIORITY_META } from "../lib/meta";

const ORDERS = {updated:"updated DESC",priority:"priority DESC, updated DESC",created:"created DESC"};
const control = "rounded-md border border-subtle bg-surface px-3 py-2 text-sm text-fg focus-visible:outline-2 focus-visible:outline-focus";

function readLayout(key:string): "cards"|"list" {
  try { return localStorage.getItem(key) === "list" ? "list" : "cards"; } catch { return "cards"; }
}

/** Personal, cross-project pins. Completion never silently removes a star. */
export function StarredPage() {
  const layoutKey = accountStorageKey("radd.starred-layout");
  const [layoutState,setLayoutState] = useState<{key:string;value:"cards"|"list"}>(()=>({key:layoutKey,value:readLayout(layoutKey)}));
  const layout = layoutState.key === layoutKey ? layoutState.value : readLayout(layoutKey);
  const changeLayout = (value:"cards"|"list") => {
    setLayoutState({key:layoutKey,value});
    try { localStorage.setItem(layoutKey,value); } catch { /* Still works for this visit. */ }
  };
  const [search,setSearch] = useState("");
  const term = useDebounced(search.trim(),250);
  const [status,setStatus] = useState("all");
  const [sort,setSort] = useState<keyof typeof ORDERS>("updated");
  const scope = status === "open" ? " AND category NOT IN (done, canceled)" : status === "completed" ? " AND category IN (done, canceled)" : "";
  const where = `starred = true${scope}${term ? ` AND title ~ ${JSON.stringify(term)}` : ""}`;
  const q = `${where} ORDER BY ${ORDERS[sort]}`;
  const count = useQuery(itemsCountQuery({},where));
  const query = useInfiniteQuery({
    queryKey:["starred-issues",q], meta:entityMeta(Entity.item), initialPageParam:null as string|null,
    queryFn:({signal,pageParam})=>api.getCursor<Item>("/items",{signal,query:{q,limit:"50",after:pageParam ?? undefined}}),
    getNextPageParam:(last:CursorPage<Item>)=>last.next ?? undefined,
  });
  const rows = [...new Map((query.data?.pages.flatMap(page=>page.rows) ?? []).map(item=>[item.id,item])).values()];
  const open = useOpenIssueRef();
  return <section aria-label="Starred issues" className="mx-auto w-full max-w-7xl p-4 sm:p-6">
    <header className="mb-5">
      <h1 className="flex items-center gap-2 text-lg font-semibold text-heading"><Star size={18} aria-hidden />Starred</h1>
      <p className="mt-1 text-sm text-fg-muted">Your personal pin board across projects, including completed issues.</p>
    </header>
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-fg-muted">Search starred issues
        <input className={control} type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search titles…" />
      </label>
      <label className="flex flex-col gap-1 text-xs text-fg-muted">Status
        <select className={control} value={status} onChange={e=>setStatus(e.target.value)}>
          <option value="all">All issues</option><option value="open">Open</option><option value="completed">Completed / canceled</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-fg-muted">Sort
        <select className={control} value={sort} onChange={e=>setSort(e.target.value as keyof typeof ORDERS)}>
          <option value="updated">Recently updated</option><option value="priority">Priority</option><option value="created">Newest issues</option>
        </select>
      </label>
      <div role="group" aria-label="Starred layout" className="flex rounded-md border border-subtle bg-surface p-1">
        {([{value:"list",label:"List",Icon:List},{value:"cards",label:"Cards",Icon:LayoutGrid}] as const).map(({value,label,Icon})=><button key={value} type="button" aria-pressed={layout===value} onClick={()=>changeLayout(value)} className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-focus ${layout===value ? "bg-elevated text-heading" : "text-fg-muted hover:text-heading"}`}><Icon size={14} aria-hidden />{label}</button>)}
      </div>
    </div>
    <p role="status" className="mb-3 text-xs text-fg-muted">{query.isPending ? "Loading starred issues…" : `${rows.length} shown`}{count.data ? ` · ${count.data.total} matching` : count.isError ? " · Total unavailable" : ""}</p>
    {query.isError && <p role="alert" className="mb-3 text-sm text-fg-muted">Could not load starred issues. {errorMessage(query.error)} <button className="underline" onClick={()=>void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}>Retry</button></p>}
    {!query.isPending && !query.isError && !rows.length && <p className="rounded-lg border border-dashed border-subtle p-6 text-sm text-fg-muted">{term || status !== "all" ? "No starred issues match these filters. Clear the search or choose All issues." : "No starred issues yet. Click the star beside an issue in a list, board or My Work to save it here."}</p>}
    {layout === "list" && rows.length > 0 && <div aria-hidden className="mb-1 hidden grid-cols-[7rem_minmax(0,1fr)_8rem_6rem_3rem_2rem] items-center gap-3 px-3 py-2 text-xs text-fg-muted lg:grid"><span>Issue</span><span>Title</span><span>Status</span><span>Priority</span><span>Owner</span><span /></div>}
    <ul aria-label={`Starred ${layout}`} className={layout === "cards" ? "grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3" : "divide-y divide-subtle overflow-hidden rounded-lg border border-subtle bg-surface"}>
      {rows.map(item=><li key={item.id} className={layout === "cards" ? "rounded-lg border border-subtle bg-surface p-4" : "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-x-3 gap-y-2 px-3 py-3 lg:grid-cols-[7rem_minmax(0,1fr)_8rem_6rem_3rem_2rem] lg:py-2"} aria-label={item.key}>
        {layout === "cards" ? <>
          <div className="mb-2 flex items-center justify-between gap-2"><span className="font-mono text-xs text-fg-muted">{item.key}</span><QuickStar item={item} /></div>
          <Link to={RoutePath.issue} params={{itemKey:item.key}} onClick={e=>void open(item.key,e)} className="block break-words text-sm font-medium text-heading hover:text-accent-text focus-visible:outline-2 focus-visible:outline-focus">{item.title}</Link>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-fg-muted"><span className="rounded bg-elevated px-2 py-1">{item.state.name}</span><span>{PRIORITY_META[item.priority].label}</span>{item.assignee && <span className="ml-auto"><Avatar user={item.assignee} size="xs" /></span>}</div>
        </> : <>
          <span className="font-mono text-xs text-fg-muted">{item.key}</span>
          <span className="col-start-2 row-start-1 flex justify-end lg:col-start-6"><QuickStar item={item} /></span>
          <Link to={RoutePath.issue} params={{itemKey:item.key}} onClick={e=>void open(item.key,e)} className="col-span-2 min-w-0 break-words text-sm font-medium text-heading hover:text-accent-text focus-visible:outline-2 focus-visible:outline-focus lg:col-span-1 lg:col-start-2 lg:row-start-1">{item.title}</Link>
          <div className="col-span-2 flex flex-wrap items-center gap-3 text-xs text-fg-muted lg:contents">
            <span className="min-w-0 break-words lg:col-start-3 lg:row-start-1">{item.state.name}</span>
            <span className="lg:col-start-4 lg:row-start-1">{PRIORITY_META[item.priority].label}</span>
            <span className="ml-auto lg:col-start-5 lg:row-start-1 lg:ml-0">{item.assignee ? <Avatar user={item.assignee} size="xs" /> : <span aria-label="Unassigned">—</span>}</span>
          </div>
        </>}
      </li>)}
    </ul>
    {query.hasNextPage && <button className={`${control} mt-4 hover:bg-elevated`} disabled={query.isFetchingNextPage} onClick={()=>void query.fetchNextPage()}>{query.isFetchingNextPage ? "Loading…" : "Show more"}</button>}
  </section>;
}
