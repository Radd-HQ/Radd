/** Related/external links (weblinks) + version-control references (vcs). */
// ---------------------------------------------------------------------------
// Related / external links (weblinks module)
// ---------------------------------------------------------------------------

export const WebLinkCategory = {
  document: "document",
  design: "design",
  spec: "spec",
  external: "external",
  other: "other",
} as const;
export type WebLinkCategoryValue = (typeof WebLinkCategory)[keyof typeof WebLinkCategory];

export interface WebLink {
  id: string;
  item_id: string;
  url: string;
  title: string;
  category: WebLinkCategoryValue;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface WebLinkCreate {
  url: string;
  title?: string;
  category?: WebLinkCategoryValue;
}

export interface WebLinkUpdate {
  url?: string;
  title?: string;
  category?: WebLinkCategoryValue;
}

// ---------------------------------------------------------------------------
// Version control references (vcs module)
// ---------------------------------------------------------------------------

export const VcsRefType = {
  branch: "branch",
  commit: "commit",
  merge_request: "merge_request",
  pull_request: "pull_request",
} as const;
export type VcsRefTypeValue = (typeof VcsRefType)[keyof typeof VcsRefType];

export const VcsProvider = {
  manual: "manual",
  gitlab: "gitlab",
  github: "github",
  forgejo: "forgejo",
} as const;
export type VcsProviderValue = (typeof VcsProvider)[keyof typeof VcsProvider];

export interface VcsLink {
  id: string;
  item_id: string;
  ref_type: VcsRefTypeValue;
  provider: VcsProviderValue;
  title: string;
  url: string;
  status: string;
  external_id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface VcsLinkCreate {
  ref_type: VcsRefTypeValue;
  provider?: VcsProviderValue;
  title: string;
  url: string;
  status?: string;
  external_id?: string;
}
