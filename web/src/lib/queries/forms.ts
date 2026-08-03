/** Intake forms, portal, public submit, mail contacts, and CSAT. */

import { queryOptions } from "@tanstack/react-query";
import { ApiError, api } from "../api";
import { Entity, entityMeta } from "../cache";
import {
  ApiPath,
  apiFormPath,
  apiItemCsatPath,
  apiItemMailContactPath,
  apiPortalFormPath,
  apiPublicCsatPath,
  apiPublicFormPath,
} from "../constants";
import { queryKeys } from "./shared";
import type {
  PortalRequest,
  PortalRequestDetail,
  Form,
  ItemCsat,
  MailContact,
  PortalForm,
  PortalGroup,
  PublicCsat,
  PublicForm,
} from "../types";

/** A project's intake forms (spec 20) — listing requires form.manage. */
export const formsQuery = (projectId: string) =>
  queryOptions({
    queryKey: queryKeys.forms(projectId),
    queryFn: () => api.get<Form[]>(ApiPath.forms, { query: { project_id: projectId } }),
    retry: false,
  });

/** A single form for the submit page (spec 20) — open to item.create on its project. */
export const formQuery = (formId: string) =>
  queryOptions({
    queryKey: queryKeys.form(formId),
    queryFn: () => api.get<Form>(apiFormPath(formId)),
  });

/**
 * The requester portal's directory (spec 73) — enabled public + shared-with-me
 * forms, grouped by project. Any signed-in user.
 */
export const portalFormsQuery = queryOptions({
  queryKey: queryKeys.portalForms,
  queryFn: () => api.get<PortalGroup[]>(ApiPath.portalForms),
  meta: entityMeta(Entity.form),
});

/** What this person has filed (RADD-785) — reporter-scoped, so it answers for
 *  a requester whose Baseline carries no read at all. */
export const portalRequestsQuery = queryOptions({
  queryKey: queryKeys.portalRequests,
  queryFn: () => api.get<PortalRequest[]>(ApiPath.portalRequests),
  staleTime: 30_000,
});

/** One eligible form's portal render payload (spec 73) — field definitions
 * inlined (a portal visitor may not read the registry); ineligible → 404. */
export const portalFormQuery = (formId: string) =>
  queryOptions({
    queryKey: queryKeys.portalForm(formId),
    queryFn: () => api.get<PortalForm>(apiPortalFormPath(formId)),
    meta: entityMeta(Entity.form),
    retry: false,
  });

/**
 * The PUBLIC render payload (spec 62) — no login, the token is the credential.
 * 404 (unknown token) / 409 (disabled) surface to the page as-is; no retry.
 */
export const publicFormQuery = (token: string) =>
  queryOptions({
    queryKey: queryKeys.publicForm(token),
    queryFn: () => api.get<PublicForm>(apiPublicFormPath(token)),
    retry: false,
  });

/**
 * The item's external requester (spec 62) — 404-quiet: most items have none,
 * so "no contact" resolves to null instead of erroring/retrying and the rail
 * chip simply doesn't render.
 */
export const mailContactQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.mailContact(itemId),
    queryFn: async (): Promise<MailContact | null> => {
      try {
        return await api.get<MailContact>(apiItemMailContactPath(itemId));
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    meta: entityMeta(Entity.item),
    retry: false,
  });

/**
 * The PUBLIC CSAT rating page's payload (spec 65) — no login, the token is the
 * credential. 404 (unknown token) surfaces to the page as-is; no retry.
 */
export const publicCsatQuery = (token: string) =>
  queryOptions({
    queryKey: queryKeys.publicCsat(token),
    queryFn: () => api.get<PublicCsat>(apiPublicCsatPath(token)),
    retry: false,
  });

/**
 * The item's ANSWERED CSAT survey (spec 65) — 404-quiet: the server 404s both
 * "never surveyed" and "not answered yet", so those resolve to null and the
 * rail chip simply doesn't render.
 */
export const itemCsatQuery = (itemId: string) =>
  queryOptions({
    queryKey: queryKeys.itemCsat(itemId),
    queryFn: async (): Promise<ItemCsat | null> => {
      try {
        return await api.get<ItemCsat>(apiItemCsatPath(itemId));
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    meta: entityMeta(Entity.item),
    retry: false,
  });

/** One request opened (RADD-796) — the requester's view, never the issue peek:
 *  that one resolves through `item.read`, which a requester holds nowhere. */
export const portalRequestDetailQuery = (key: string) =>
  queryOptions({
    queryKey: queryKeys.portalRequest(key),
    queryFn: () => api.get<PortalRequestDetail>(`${ApiPath.portalRequests}/${key}`),
    enabled: Boolean(key),
  });
