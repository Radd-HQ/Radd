/**
 * The wiki's addresses (spec 124; RADD-1392: the pages plugin owns them, and the host's router
 * mounts its route components at these paths).
 *
 * - `/pages` — the spaces index, and the permalink resolver (`/pages?pageId=<number>`);
 * - `/pages/<space>` — a space's tree; `/pages/<space>/<slug>/<slug>/…` — a page, a PATH through
 *   the tree carried by the splat. A single segment may be a number or an id: such links resolve
 *   and the page view rewrites the URL to the canonical path, so no link ever shared can rot;
 * - `/print/pages/<space>/<path>` — the print view (RADD-733), a TOP-LEVEL route outside the app
 *   layout, under its own prefix because nothing may hang a literal after a path.
 */
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
 * The two ways to address a page (RADD-1233), and the ONE place that builds them.
 *
 * - `pageLink(space, path)` — the readable address: `/pages/<space>/<slug>/<slug>`.
 *   For anything that already holds the page's `path` (the tree, a breadcrumb,
 *   a full page read, backlinks, label lists).
 * - `pagePermalink(key)` — `/pages?pageId=<number>`: resolves and redirects to
 *   the current path. For anything that holds an id but no path (search hits,
 *   deflection, the issue's Docs row, notifications, audit refs), and for every
 *   link the SERVER emits, because it survives renames and moves.
 *
 * Nothing else may assemble a page URL from a slug: a slug is one segment of a
 * path, and a path assembled from the wrong segment is a page that "does not
 * exist".
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

/** The permalink as a plain href. */
export function pagePermalinkHref(key: string | number): string {
  return `/pages?pageId=${encodeURIComponent(String(key))}`;
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
