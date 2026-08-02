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
  /** Spec 74: readable without login under /kb (doc.manage toggles it). */
  public: boolean;
  /** Live (non-archived) page count, hydrated by the list endpoint. */
  page_count: number;
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
  /** Spec 74: toggle the no-login /kb readability (doc.manage). */
  public?: boolean;
}

/** Flat tree row from GET /page-spaces/{id}/pages — the client builds the tree. */
export interface PageSummary {
  id: string;
  parent_id: string | null;
  title: string;
  position: number;
  has_children: boolean;
  updated_at: string;
}

export interface DocBreadcrumb {
  id: string;
  title: string;
}

export interface Page {
  id: string;
  space_id: string;
  parent_id: string | null;
  title: string;
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
  breadcrumb: DocBreadcrumb[];
}

export interface PageCreate {
  space_id: string;
  parent_id?: string | null;
  title: string;
  body?: string;
}

/** Omitted = unchanged; parent_id null moves to root; a stale expected_version 409s. */
export interface PageUpdate {
  title?: string;
  body?: string;
  parent_id?: string | null;
  position?: number;
  expected_version?: number;
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

// ---------------------------------------------------------------------------
// Public pages (spec 74) — trimmed no-login shapes under /public/kb
// ---------------------------------------------------------------------------

/** GET /public/kb/spaces — a public space's card. */
export interface PublicPageSpace {
  id: string;
  name: string;
  slug: string;
  description: string;
}

/** GET /public/kb/spaces/{id}/tree — one non-archived flat tree row. */
export interface PublicPageNode {
  id: string;
  parent_id: string | null;
  title: string;
  position: number;
}

/** GET /public/kb/pages/{id} — body + breadcrumb only (markdown renders client-side). */
export interface PublicPagesPage {
  id: string;
  space_id: string;
  title: string;
  body: string;
  /** Ancestors, root first (excludes the page itself). */
  breadcrumb: DocBreadcrumb[];
  updated_at: string;
}

/** GET /public/forms/{token}/deflect (spec 74) — public-KB docs ONLY (the
 * authed DeflectResponse's docs shape; resolved issues stay internal). */
export interface PublicDeflectResponse {
  docs: DeflectPage[];
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
