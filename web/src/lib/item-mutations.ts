import {
  useMutation,
  useQueryClient,
  type InfiniteData,
  type QueryClient,
} from "@tanstack/react-query";
import { api, errorMessage } from "./api";
import { Entity, invalidateEntities } from "./cache";
import { pushToast } from "./toast";
import {
  ApiPath,
  apiItemArchivePath,
  apiItemLinkPath,
  apiItemLinksPath,
  apiItemPath,
  apiItemRankPath,
  apiItemStarPath,
} from "./constants";
import { queryKeys } from "./queries";
import { IntakeCommit } from "./types";
import type {
  IntakeCommitValue,
  IntakeVerdict,
  Item,
  ItemCreate,
  ItemKindValue,
  ItemLinkCreate,
  ItemUpdate,
  View,
} from "./types";

/** Shared TanStack Query mutations for items (board, detail panel, modal). */

/**
 * Refresh every surface holding items after a mutation. Items are cached under
 * many keys (board list / saved view / SLQ list / detail / by-key panel); rather
 * than list them, we invalidate by ENTITY — each item query self-declares
 * `meta.entities: [item]`, so any query (incl. ones added later by new modules)
 * is caught automatically. See lib/cache.ts.
 */
function invalidateItemCaches(queryClient: QueryClient) {
  void invalidateEntities(queryClient, Entity.item);
}

/** Seed the freshly-returned item into both single-item caches (detail + panel)
 *  so those surfaces update instantly, ahead of the invalidation refetch. */
function cacheItem(queryClient: QueryClient, item: Item) {
  queryClient.setQueryData(queryKeys.item(item.id), item);
  queryClient.setQueryData(queryKeys.itemByKey(item.key), item);
}

/** Paged item caches (spec 55): board/roadmap/list and the view page all hold
 *  `InfiniteData<Item[]>` — optimistic patches map over every loaded page. */
type ItemPages = InfiniteData<Item[], number>;

const mapPages =
  (fn: (item: Item) => Item) =>
  (old: ItemPages | undefined): ItemPages | undefined =>
    old && { ...old, pages: old.pages.map((page) => page.map(fn)) };

/** Apply a flat-list transform to a paged cache, re-chunking to the original
 *  page sizes (safe for same-count transforms like reorder). */
function transformPages(
  old: ItemPages | undefined,
  transform: (flat: Item[]) => Item[],
): ItemPages | undefined {
  if (!old) return old;
  const lengths = old.pages.map((page) => page.length);
  const flat = transform(old.pages.flat());
  const pages: Item[][] = [];
  let start = 0;
  for (const length of lengths) {
    pages.push(flat.slice(start, start + length));
    start += length;
  }
  return { ...old, pages };
}

/** PATCH an item (detail panel edits); syncs every item cache so all surfaces update live. */
export function useUpdateItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ itemId, patch }: { itemId: string; patch: ItemUpdate }) =>
      api.patch<Item>(apiItemPath(itemId), patch),
    onError: (error) => pushToast(errorMessage(error)),
    onSuccess: (updated) => {
      cacheItem(queryClient, updated);
    },
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/** One PATCH of a roadmap gesture commit (spec 77). */
export interface RoadmapDatePatch {
  itemId: string;
  patch: ItemUpdate;
  /** RADD-1151: the full item when the roadmap's base fetch lacks it (an
   *  unscheduled child a plan verb brings in), so the draft can DRAW it
   *  before Save — the tray drop's INSERT, for plans. */
  insert?: Item;
  /** Merged into every cached copy of the item for the optimistic paint. */
  optimistic: Partial<Item>;
}

/**
 * Sequential multi-PATCH for roadmap gestures (spec 77): a bar move/resize —
 * optionally paired with its parent epic's auto-stretch — commits as ONE
 * optimistic unit against the roadmap VIEW's item cache (spec 79: roadmaps are
 * saved views, so the paged `viewItems` cache is the one on screen). Either
 * PATCH failing rolls the whole set back and toasts once; the settle
 * invalidation refetches server truth either way (a child that landed before
 * the epic PATCH failed stays valid server-side — an epic narrower than a
 * child is legal).
 */
export function useRoadmapItemPatch(view: Pick<View, "id" | "query_string"> | undefined) {
  const queryClient = useQueryClient();
  const listKey = queryKeys.viewItems(view?.id ?? "", view?.query_string ?? "");

  return useMutation({
    mutationFn: async ({ patches }: { patches: RoadmapDatePatch[] }) => {
      const updated: Item[] = [];
      for (const { itemId, patch } of patches) {
        updated.push(await api.patch<Item>(apiItemPath(itemId), patch));
      }
      return updated;
    },
    onMutate: async ({ patches }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<ItemPages>(listKey);
      const byId = new Map(patches.map((entry) => [entry.itemId, entry.optimistic]));
      const apply = (item: Item): Item => {
        const optimistic = byId.get(item.id);
        return optimistic ? { ...item, ...optimistic } : item;
      };
      queryClient.setQueryData<ItemPages>(listKey, mapPages(apply));
      return { previous };
    },
    onError: (error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(listKey, context.previous);
      pushToast(errorMessage(error));
    },
    onSuccess: (updated) => {
      for (const item of updated) cacheItem(queryClient, item);
    },
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/**
 * Optimistic PATCH of an item inside a saved view's item list (spec 24):
 * cross-bucket drag, the context menu, and bulk actions all route through here.
 * `optimistic` is merged into the cached item so it re-buckets immediately;
 * the server response reconciles on success, and the view refetches on settle
 * for true SLQ ordering. Rolls back the whole list on error.
 */
export function useUpdateItemInView(view: Pick<View, "id" | "query_string"> | undefined) {
  const queryClient = useQueryClient();
  const listKey = queryKeys.viewItems(view?.id ?? "", view?.query_string ?? "");

  return useMutation({
    mutationFn: ({ itemId, patch }: { itemId: string; patch: ItemUpdate; optimistic?: Partial<Item> }) =>
      api.patch<Item>(apiItemPath(itemId), patch),
    onMutate: async ({ itemId, optimistic }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<ItemPages>(listKey);
      if (optimistic) {
        queryClient.setQueryData<ItemPages>(
          listKey,
          mapPages((item) => (item.id === itemId ? { ...item, ...optimistic } : item)),
        );
      }
      return { previous };
    },
    onError: (error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(listKey, context.previous);
      // Context-menu / bulk state changes can hit the transition guards (spec 61).
      pushToast(errorMessage(error));
    },
    onSuccess: (updated) => {
      cacheItem(queryClient, updated);
      queryClient.setQueryData<ItemPages>(
        listKey,
        mapPages((item) => (item.id === updated.id ? updated : item)),
      );
    },
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/**
 * Toggle a personal star (spec 24) inside a saved view's item list. Optimistic:
 * flips `starred` on the cached item; PUT stars, DELETE unstars. Available to
 * anyone who can read the item (no item.update needed).
 */
export function useToggleStar(view: Pick<View, "id" | "query_string"> | undefined) {
  const queryClient = useQueryClient();
  const listKey = queryKeys.viewItems(view?.id ?? "", view?.query_string ?? "");

  return useMutation({
    mutationFn: async ({ itemId, star }: { itemId: string; star: boolean }) => {
      if (star) await api.put<Item>(apiItemStarPath(itemId));
      else await api.delete<void>(apiItemStarPath(itemId));
    },
    onMutate: async ({ itemId, star }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<ItemPages>(listKey);
      queryClient.setQueryData<ItemPages>(
        listKey,
        mapPages((item) => (item.id === itemId ? { ...item, starred: star } : item)),
      );
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(listKey, context.previous);
    },
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/**
 * Toggle a personal star from a non-view surface (the issue detail / side panel).
 * No local cache to splice; invalidating every item family refreshes `starred`
 * on all surfaces.
 */
export function useToggleStarOnItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ itemId, star }: { itemId: string; star: boolean }) => {
      if (star) await api.put<Item>(apiItemStarPath(itemId));
      else await api.delete<void>(apiItemStarPath(itemId));
    },
    onSettled: () => invalidateEntities(queryClient, Entity.item),
  });
}

/**
 * Drag-to-rank inside a saved view sorted by rank (spec 24). Optimistically
 * splices the item to its new array position (the list renders in server rank
 * order); reconciles on settle. Neighbours are the items the drop landed between.
 */
export function useReorderItem(view: Pick<View, "id" | "query_string"> | undefined) {
  const queryClient = useQueryClient();
  const listKey = queryKeys.viewItems(view?.id ?? "", view?.query_string ?? "");

  return useMutation({
    mutationFn: ({
      itemId,
      afterId,
      beforeId,
    }: {
      itemId: string;
      afterId: string | null;
      beforeId: string | null;
    }) => api.patch<Item>(apiItemRankPath(itemId), { after_id: afterId, before_id: beforeId }),
    onMutate: async ({ itemId, afterId, beforeId }) => {
      await queryClient.cancelQueries({ queryKey: listKey });
      const previous = queryClient.getQueryData<ItemPages>(listKey);
      queryClient.setQueryData<ItemPages>(listKey, (old) =>
        transformPages(old, (flat) => {
          const moving = flat.find((item) => item.id === itemId);
          if (!moving) return flat;
          const without = flat.filter((item) => item.id !== itemId);
          let index = without.length;
          if (beforeId) {
            const i = without.findIndex((item) => item.id === beforeId);
            if (i !== -1) index = i;
          } else if (afterId) {
            const i = without.findIndex((item) => item.id === afterId);
            if (i !== -1) index = i + 1;
          }
          return [...without.slice(0, index), moving, ...without.slice(index)];
        }),
      );
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(listKey, context.previous);
    },
    onSuccess: (updated) => cacheItem(queryClient, updated),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/**
 * Add a dependency link (POST /items/{id}/links). The backend returns the
 * updated source item; both ends refresh — the target item's detail gains the
 * mirrored incoming edge, so every `["item", …]` detail cache is invalidated.
 * 409 conflicts (self-link, cross-project, cycle, duplicate) reject to the caller.
 */
export function useAddItemLink(_projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ itemId, body }: { itemId: string; body: ItemLinkCreate }) =>
      api.post<Item>(apiItemLinksPath(itemId), body),
    onSuccess: (updated) => cacheItem(queryClient, updated),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/** Remove a dependency link (DELETE /items/{id}/links/{link_id}). */
export function useRemoveItemLink(_projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ itemId, linkId }: { itemId: string; linkId: string }) =>
      api.delete<void>(apiItemLinkPath(itemId, linkId)),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/**
 * Create through intake validation (spec 119) — one round trip that both checks
 * and creates.
 *
 * It REPLACED `useCreateItem` rather than taking a flag on it, because the
 * result shape differs: this one can answer "nothing was created, and here is
 * why", which a caller has to handle, and hiding that behind an option is how a
 * surface ends up silently discarding a verdict. `created` is null exactly when
 * the draft did not survive. (`useCreateItem` had exactly one caller, the New
 * Item modal, and kept compiling with none — deleted here rather than left as a
 * second way to create an item that skips the checks by construction.)
 */
export function useValidateItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ body, commit }: { body: ItemCreate; commit?: IntakeCommitValue }) =>
      api.post<{ verdict: IntakeVerdict; created: Item | null }>(ApiPath.itemsValidate, {
        ...body,
        commit: commit ?? IntakeCommit.pass,
      }),
    onSuccess: (result) => {
      if (result.created) cacheItem(queryClient, result.created);
    },
    onSettled: (result) => {
      // Only when something was actually written: a rejected draft rolled back,
      // so invalidating every item cache would be a refetch storm buying nothing.
      if (result?.created) invalidateItemCaches(queryClient);
    },
  });
}


/** Soft archive/unarchive (spec 38) — hidden from lists by default. */
/** Merge a duplicate into its survivor (RADD-1090): everything repoints,
 * the source closes canceled with a `duplicates` link. Returns the SURVIVOR. */
export function useMergeItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sourceId, targetKey }: { sourceId: string; targetKey: string }) =>
      api.post<Item>(`${ApiPath.items}/${sourceId}/merge`, { target_key: targetKey }),
    onSuccess: (survivor) => {
      cacheItem(queryClient, survivor);
      pushToast(`Merged into ${survivor.key} — comments, time and links moved`);
    },
    onError: (error) => pushToast(errorMessage(error)),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/** Convert kind (RADD-1089): epic <-> issue; refusals name the blocker. */
export function useConvertItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, kind }: { itemId: string; kind: ItemKindValue }) =>
      api.post<Item>(`${ApiPath.items}/${itemId}/convert`, { kind }),
    onSuccess: (updated) => {
      cacheItem(queryClient, updated);
      pushToast(`Now ${updated.kind === "epic" ? "an" : "a"} ${updated.kind}`);
    },
    onError: (error) => pushToast(errorMessage(error)),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/** Clone (RADD-1088): shape copied, trail not — server drops what the actor
 * cannot write and links the clone `relates` to the original. */
export function useCloneItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, includeSubtasks }: { itemId: string; includeSubtasks?: boolean }) =>
      api.post<Item>(`${ApiPath.items}/${itemId}/clone`, {
        include_subtasks: includeSubtasks ?? false,
      }),
    onSuccess: (created) => {
      cacheItem(queryClient, created);
      pushToast(`Cloned as ${created.key}`);
    },
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

export function useArchiveItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, archived }: { itemId: string; archived: boolean }) =>
      archived
        ? api.put<Item>(apiItemArchivePath(itemId))
        : api.delete<Item>(apiItemArchivePath(itemId)),
    onSuccess: (updated) => cacheItem(queryClient, updated),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}

/** Hard delete (spec 38): project.manage; the audit trail keeps the history. */
export function useDeleteItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (itemId: string) => api.delete<void>(apiItemPath(itemId)),
    onSettled: () => invalidateItemCaches(queryClient),
  });
}
