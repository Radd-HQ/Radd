/** Mail sources, senders, routing rules and kind presets (RADD-958/969):
 *  Settings → Email. Every read here is gated on `global.manage` server-side. */

import { queryOptions } from "@tanstack/react-query";
import { api } from "../api";
import { ApiPath, apiMailSourceRulesPath } from "../constants";
import { queryKeys } from "./shared";
import type { MailKinds, MailRule, MailSender, MailSource } from "../types";

/** Where mail arrives. Secrets never leave the server — `has_secret` only. */
export const mailSourcesQuery = () =>
  queryOptions({
    queryKey: queryKeys.mailSources,
    queryFn: () => api.get<MailSource[]>(ApiPath.mailSources),
    staleTime: 30_000,
  });

/** The relays mail goes out through. */
export const mailSendersQuery = () =>
  queryOptions({
    queryKey: queryKeys.mailSenders,
    queryFn: () => api.get<MailSender[]>(ApiPath.mailSenders),
    staleTime: 30_000,
  });

/** One source's routing chain, position-ordered top-down. */
export const mailRulesQuery = (sourceId: string) =>
  queryOptions({
    queryKey: queryKeys.mailRules(sourceId),
    queryFn: () => api.get<MailRule[]>(apiMailSourceRulesPath(sourceId)),
  });

/**
 * What each kind answers on the operator's behalf (RADD-969) — the spec-110
 * `ssoKindsQuery` shape. Static server-side catalog, so it never goes stale:
 * both dialogs share the one fetch, and neither carries its own copy of
 * `smtp.gmail.com`.
 */
export const mailKindsQuery = () =>
  queryOptions({
    queryKey: queryKeys.mailKinds,
    queryFn: () => api.get<MailKinds>(ApiPath.mailKinds),
    staleTime: Infinity,
  });
