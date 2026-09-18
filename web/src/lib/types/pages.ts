/** Pages (docs, spec 43) + public pages (spec 74) + KB deflection (spec 66). */
// ---------------------------------------------------------------------------
// Pages (docs module — spec 43)
// ---------------------------------------------------------------------------

export interface PageSpace {
  id: string;
  name: string;
  slug: string;
  description: string;
  position: number;
  /** Spec 121 §5: DERIVED — the Public role is granted to Anyone on this space
   *  (written through PUT /page-spaces/{id}/public-access). */
  public: boolean;
  /** Live (non-archived) page count, hydrated by the list endpoint. */
  page_count: number;
  /** RADD-814: the caller's per-SPACE permission union (the ProjectRead
   * .permissions analogue) — what `can({ space })` resolves against. */
  permissions?: string[];
  created_at: string;
  updated_at: string;
}

export interface PageSpaceCreate {
  name: string;
  /** Omitted -> derived from the name (slugs are cosmetic; URLs use ids). */
  slug?: string;
  description?: string;
  position?: number;
}

export interface PageSpaceUpdate {
  name?: string;
  slug?: string;
  description?: string;
  position?: number;
}

/** One entry in the editor's insert menu (RADD-709), from the kernel registry.
 *  `params_schema` is JSON Schema — the picker reads `properties`/`required`/
 *  `default` from it to pre-fill an inserted block. */
export interface PageExtensionSpec {
  name: string;
  label: string;
  description: string;
  params_schema: { properties?: Record<string, unknown>; required?: string[] };
  icon: string;
  /** The plugin that contributed it — the insert menu's grouping (RADD-748).
   *  The SERVER says where each came from; the client must not guess from a
   *  plugin name it may never have seen. */
  source: string;
}

/** A page that links to this one (RADD-713). Carries the space slug because a
 *  backlink may come from another space and the URL needs both segments. */
export interface PageBacklink {
  id: string;
  title: string;
  slug: string;
  space_id: string;
  space_slug: string;
  updated_at: string;
}

/** A page carrying a label (RADD-718), for `radd:label-list`. */
export interface PageLabelled {
  id: string;
  title: string;
  slug: string;
  space_slug: string;
  updated_at: string;
}

/** A shape a recurring page starts from (RADD-712). */
export interface PageTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  body: string;
  space_id: string | null;
}

/** Flat tree row from GET /page-spaces/{id}/pages — the client builds the tree. */
export interface PageSummary {
  id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  position: number;
  has_children: boolean;
  updated_at: string;
  /** RADD-718 — hydrated in one query for the whole tree. */
  labels: string[];
  /** RADD-1228 — only the `include_archived` listing sets it; a live page
   *  hidden under an archived ancestor carries null. */
  archived_at?: string | null;
}

export interface PageBreadcrumb {
  id: string;
  title: string;
  slug: string;
}

export interface Page {
  id: string;
  space_id: string;
  parent_id: string | null;
  title: string;
  slug: string;
  body: string;
  position: number;
  /** Optimistic-concurrency guard: PATCH sends it back as expected_version. */
  version: number;
  created_by: string;
  updated_by: string;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  space: PageSpace;
  /** Ancestors, root first (excludes the page itself). */
  breadcrumb: PageBreadcrumb[];
  /** RADD-718 */
  labels: string[];
}

export interface PageCreate {
  space_id: string;
  parent_id?: string | null;
  title: string;
  body?: string;
  /** Template NAME to render the initial body from (RADD-712); body wins if both given. */
  template?: string;
}

/** Omitted = unchanged; parent_id null moves to root; a stale expected_version 409s. */
export interface PageUpdate {
  title?: string;
  /** RADD-860: the deliberate URL change (server suffixes on collision). */
  slug?: string;
  body?: string;
  parent_id?: string | null;
  position?: number;
  expected_version?: number;
  /** Spec 122: the body comes from a live room's elected saver — the server
   *  skips the `expected_version` check for this session's writes. */
  collab_session?: string;
  /** Spec 122: the session's last save; the server records a version row. */
  final?: boolean;
}

export interface PageVersionMeta {
  version: number;
  title: string;
  author_id: string;
  created_at: string;
}

export interface DocVersion extends PageVersionMeta {
  body: string;
}

/** An issue linked to a page, hydrated for display. */
export interface PageLinkedItem {
  item_id: string;
  key: string;
  title: string;
  state: string;
  state_category: string;
  /** The page's TEXT mentions this issue (RADD-943): the link is reconciled on
   *  every save, so it is not the reader's to unlink — edit the body instead. */
  derived: boolean;
}

/** A page linked to an issue (the issue page's Pages row). */
export interface ItemPageRef {
  page_id: string;
  space_id: string;
  title: string;
  space_name: string;
}

export interface PageSearchResult {
  page_id: string;
  space_id: string;
  title: string;
  /** ts_headline fragment with <b>…</b> marks. */
  snippet: string | null;
}

export interface PageSearchResponse {
  results: PageSearchResult[];
}



/** GET /search/deflect (spec 66) — KB deflection under the new-issue title:
 * pages pages that may already answer it + previously RESOLVED items. */
export interface DeflectPage {
  id: string;
  space_id: string;
  title: string;
  space_name: string;
}

export interface DeflectItem {
  key: string;
  title: string;
}

export interface DeflectResponse {
  docs: DeflectPage[];
  items: DeflectItem[];
}

/** PUT /page-spaces/{id}/public-access (spec 121 §5). */
export interface SpacePublicAccessUpdate {
  public: boolean;
}
