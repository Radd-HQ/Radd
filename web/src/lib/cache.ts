import type { QueryClient } from "@tanstack/react-query";
import { invalidateEntities as invalidateTagged } from "@radd/plugin-sdk";

/**
 * Invalidation by ENTITY, not query key: a read declares what it caches
 * (`meta: entityMeta(Entity.item)`), a mutation invalidates by entity
 * (`invalidateEntities(qc, Entity.item)`), so queries added later are covered
 * automatically. See docs/modules.md → "Cache invalidation".
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
  serviceAccount: "serviceAccount",
  cardLayoutPreset: "cardLayoutPreset",
  docSpace: "docSpace",
  page: "page",
  dashboard: "dashboard",
} as const;

export type EntityTag = (typeof Entity)[keyof typeof Entity];

interface EntityMeta extends Record<string, unknown> {
  entities: EntityTag[];
  projectId?: string;
  itemId?: string;
  itemDetail?: boolean;
}

export function itemEntityMeta(itemId: string, ...entities: EntityTag[]): EntityMeta {
  return { entities, itemId };
}

/** Spread into a query's `meta` to declare which entities its data caches. */
export function entityMeta(...entities: EntityTag[]): EntityMeta {
  return { entities };
}

/** Declare a query's explicit server-side project filter; absent = all projects. */
export function projectEntityMeta(projectId: string | null | undefined, ...entities: EntityTag[]): EntityMeta {
  return {entities, projectId: projectId || undefined};
}

/** The SDK's invalidation, typed to the host's entity tags. List every entity a mutation changes
 *  (a comment also changes its item's `comment_count`). */
export function invalidateEntities(queryClient: QueryClient, ...entities: EntityTag[]) {
  return invalidateTagged(queryClient, ...entities);
}
