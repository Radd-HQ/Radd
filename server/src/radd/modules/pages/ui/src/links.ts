/** The wiki's routes (spec 124). A page is `/pages/<space>/<slug>/…` (a splat PATH); `/pages?pageId=<n>`
 *  is the permalink; `/print/pages/…` sits under its own prefix because nothing may follow a splat. */
export const PageRoute = {
  pages: "/pages",
  space: "/pages/$spaceSlug",
  page: "/pages/$spaceSlug/$",
  print: "/print/pages/$spaceSlug/$",
  /** Page spaces admin (spec 43): this plugin's page under the settings catch-all. */
  settings: "/settings/pages",
} as const;

/** A link to the Page spaces settings page, which the settings catch-all mounts. */
export const spacesSettingsLink = { to: "/settings/$", params: { _splat: "pages" } } as const;

/**
 * The ONE place page URLs are built. `pageLink(space, path)` when you hold the page's `path`;
 * `pagePermalink(key)` when you hold only an id/number, and for anything the server emits — it
 * survives renames and moves. Never assemble a page URL from a slug: a slug is one path segment.
 */

export interface PageLinkProps {
  to: typeof PageRoute.page;
  params: { spaceSlug: string; _splat: string };
}

export interface PagePermalinkProps {
  to: typeof PageRoute.pages;
  search: { pageId: string | number; comment?: string };
}

export function pageLink(spaceSlug: string, path: string): PageLinkProps {
  return { to: PageRoute.page, params: { spaceSlug, _splat: path } };
}

export function pagePermalink(key: string | number, comment?: string): PagePermalinkProps {
  // A NUMBER, not its string: the router JSON-encodes search values, and a
  // string "113" would land in the bar as `?pageId=%22113%22`.
  const numeric = typeof key === "number" ? key : /^\d+$/.test(key) ? Number(key) : key;
  // RADD-1297: a comment link rides through the permalink's redirect.
  return { to: PageRoute.pages, search: { pageId: numeric, ...(comment ? { comment } : {}) } };
}

/** The readable address as a plain href — for `window.open`, footers, copy. */
export function pageHref(spaceSlug: string, path: string): string {
  return `/pages/${encodeURIComponent(spaceSlug)}/${encodePath(path)}`;
}

/** The print view of a page (RADD-733): a top-level route, outside the shell. */
export function pagePrintHref(spaceSlug: string, path: string, subpages: boolean): string {
  const query = subpages ? "?subpages=1" : "";
  return `/print/pages/${encodeURIComponent(spaceSlug)}/${encodePath(path)}${query}`;
}

/** Encode each segment, keep the slashes — a path IS its slashes. */
export function encodePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}
