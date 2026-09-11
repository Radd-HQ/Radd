import type { QueryClient } from "@tanstack/react-query";

/**
 * Cross-cache invalidation by ENTITY (not by query key).
 *
 * The problem: one entity (e.g. an item) is cached under many separate query
 * keys — `["items"]`, `["viewItems"]`, `["slqItems"]`, `["item"]`,
 * `["itemByKey"]` — so a mutation has to remember to invalidate every one of
 * them, and a NEW query that caches items is silently missed by existing
 * mutations (the exact bug that made edits not appear live).
 *
 * The fix: decouple queries from mutations.
 *   • A read query DECLARES which entities its data holds:
 *       useQuery({ ..., meta: entityMeta(Entity.item) })
 *   • A mutation INVALIDATES by entity, never by key:
 *       onSettled: () => invalidateEntities(queryClient, Entity.item)
 *
 * Now any query tagged with an entity is refreshed by every mutation that
 * touches that entity — including queries added later by other modules. Neither
 * side needs to know about the other. This is the convention every module
 * follows (see docs/modules.md → "Cache invalidation").
 */

/** One tag per cacheable domain entity — extend this as modules are added. */
export const Entity = {
  item: "item",
  comment: "comment",
  cycle: "cycle",
  cycleSeries: "cycleSeries",
  release: "release",
  view: "view",
  label: "label",
  team: "team",
  group: "group",
  field: "field",
  accessGrant: "accessGrant",
  worklog: "worklog",
  workCategory: "workCategory",
  automation: "automation",
  form: "form",
  role: "role",
  member: "member",
  project: "project",
  transition: "transition",
  webLink: "webLink",
  vcsLink: "vcsLink",
  notification: "notification",
  watcher: "watcher",
  attachment: "attachment",
  cannedResponse: "cannedResponse",
  forgejoConnection: "forgejoConnection",
  forgejoRepo: "forgejoRepo",
  serviceAccount: "serviceAccount",
  cardLayoutPreset: "cardLayoutPreset",
  slaPolicy: "slaPolicy",
  docSpace: "docSpace",
  page: "page",
  dashboard: "dashboard",
} as const;

export type EntityTag = (typeof Entity)[keyof typeof Entity];

interface EntityMeta extends Record<string, unknown> {
  entities: EntityTag[];
  projectId?: string;
}

/** Spread into a query's `meta` to declare which entities its data caches. */
export function entityMeta(...entities: EntityTag[]): EntityMeta {
  return { entities };
}

/** Declare a query's explicit server-side project filter; absent = all projects. */
export function projectEntityMeta(projectId: string | null | undefined, ...entities: EntityTag[]): EntityMeta {
  return {entities, projectId: projectId || undefined};
}

/**
 * Invalidate every query whose `meta.entities` includes any of `entities` —
 * across all cache families. Active queries refetch immediately (reads "live").
 * A mutation lists every entity it can change, e.g. commenting touches the
 * comment AND the item (its `comment_count`): `invalidateEntities(qc, Entity.comment, Entity.item)`.
 */
export function invalidateEntities(queryClient: QueryClient, ...entities: EntityTag[]) {
  const wanted = new Set<EntityTag>(entities);
  return queryClient.invalidateQueries({
    predicate: (query) => {
      const tags = (query.meta as EntityMeta | undefined)?.entities;
      return Array.isArray(tags) && tags.some((tag) => wanted.has(tag));
    },
  });
}
