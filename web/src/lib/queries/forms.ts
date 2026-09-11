/** Intake forms, portal, public submit, mail contacts, and CSAT. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiFormPath,
  apiPortalFormPath,
  apiPublicCsatPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  PortalRequest,
  PortalRequestDetail,
  Form,
  PortalForm,
  PortalGroup,
  PublicCsat,
} from "../types";

/** A project's intake forms (spec 20) — listing requires form.manage. */
export const formsQuery = (projectId: string, includeShares = true) =>
  queryOptions({
    queryKey: includeShares ? queryKeys.forms(projectId) : [...queryKeys.forms(projectId), "definitions"],
    queryFn: ({ signal }) => api.get<Form[]>(ApiPath.forms, { signal, query: { project_id: projectId, include_shares: String(includeShares) } }),
    retry: false,
    meta: entityMeta(Entity.form, Entity.project, Entity.role, Entity.member, Entity.team, Entity.group),
  });

/** A single form for the submit page (spec 20) — open to item.create on its project. */
export const formQuery = (formId: string) =>
  queryOptions({
    queryKey: queryKeys.form(formId),
    queryFn: ({ signal }) => api.get<Form>(apiFormPath(formId), { signal }),
  });

/**
 * The requester portal's directory (spec 73) — enabled public + shared-with-me
 * forms, grouped by project. Any signed-in user.
 */
export const portalFormsQuery = queryOptions({
  queryKey: queryKeys.portalForms,
  queryFn: ({ signal }) => api.get<PortalGroup[]>(ApiPath.portalForms, { signal }),
  meta: entityMeta(Entity.form),
});

/** What this person has filed (RADD-785) — reporter-scoped, so it answers for
 *  a requester whose Baseline carries no read at all. */
export const portalRequestsQuery = queryOptions({
  queryKey: queryKeys.portalRequests,
  queryFn: ({ signal }) => api.get<PortalRequest[]>(ApiPath.portalRequests, { signal }),
  staleTime: 30_000,
});

/** One eligible form's portal render payload (spec 73) — field definitions
 * inlined (a portal visitor may not read the registry); ineligible → 404. */
export const portalFormQuery = (formId: string) =>
  queryOptions({
    queryKey: queryKeys.portalForm(formId),
    queryFn: ({ signal }) => api.get<PortalForm>(apiPortalFormPath(formId), { signal }),
    meta: entityMeta(Entity.form),
    retry: false,
  });

/**
 * The PUBLIC render payload (spec 62) — no login, the token is the credential.
 * 404 (unknown token) / 409 (disabled) surface to the page as-is; no retry.
 */

/**
 * The PUBLIC CSAT rating page's payload (spec 65) — no login, the token is the
 * credential. 404 (unknown token) surfaces to the page as-is; no retry.
 */
export const publicCsatQuery = (token: string) =>
  queryOptions({
    queryKey: queryKeys.publicCsat(token),
    queryFn: ({ signal }) => api.get<PublicCsat>(apiPublicCsatPath(token), { signal }),
    retry: false,
  });

/** One request opened (RADD-796) — the requester's view, never the issue peek:
 *  that one resolves through `item.read`, which a requester holds nowhere. */
export const portalRequestDetailQuery = (key: string) =>
  queryOptions({
    queryKey: queryKeys.portalRequest(key),
    queryFn: ({ signal }) => api.get<PortalRequestDetail>(`${ApiPath.portalRequests}/${key}`, { signal }),
    enabled: Boolean(key),
  });

/** Where to upload a submission's files before the item exists (RADD-800).
 *  DERIVED from the caller server-side — the client never picks this id. */
export const portalStagingAreaQuery = queryOptions({
  queryKey: [...queryKeys.portalForms, "staging-area"] as const,
  queryFn: ({ signal }) => api.get<{ entity_id: string }>(`${ApiPath.portalForms}/staging-area`, { signal }),
  staleTime: Infinity,
});

export const FORM_SHARING_PAGE_SIZE = 50;
export interface FormSharingRow { id: string; user_id: string | null; team_id: string | null; created_at: string; subject_name: string | null; active: boolean | null }
export const FormShareKind = { user: "user", team: "team" } as const;
export type FormShareKindValue = typeof FormShareKind[keyof typeof FormShareKind];
export const formSharingQuery = (id: string, q = "", page = 0) => queryOptions({
  queryKey: [...queryKeys.form(id), "sharing", q.trim(), page],
  queryFn: ({ signal }) => api.getPaged<FormSharingRow>(`${apiFormPath(id)}/sharing`, { signal, query: {
    q: q.trim(), limit: String(FORM_SHARING_PAGE_SIZE), offset: String(page * FORM_SHARING_PAGE_SIZE),
  } }), meta: entityMeta(Entity.form, Entity.project, Entity.role, Entity.member, Entity.team, Entity.group),
});
export const formShareCandidatesQuery = (id: string, kind: FormShareKindValue, q = "", page = 0) => queryOptions({
  queryKey: [...queryKeys.form(id), "sharing-candidates", kind, q.trim(), page],
  queryFn: ({ signal }) => api.getPaged<{ value: string; label: string; hint: string }>(`${apiFormPath(id)}/sharing/candidates`, { signal, query: {
    kind, q: q.trim(), limit: String(FORM_SHARING_PAGE_SIZE), offset: String(page * FORM_SHARING_PAGE_SIZE),
  } }), meta: entityMeta(Entity.form, Entity.project, Entity.role, Entity.member, Entity.team, Entity.group),
});
