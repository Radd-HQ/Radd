import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";
import type { MailKinds, MailRule, MailSender, MailSource } from "./types";

/** The mail config endpoints (all `global.manage` server-side). */
const id = (value: string) => encodeURIComponent(value);

export const MailPath = {
  sources: "/mail/sources",
  senders: "/mail/senders",
  /** Per-kind defaults — what the add-a-source/sender form prefills itself with. */
  kinds: "/mail/kinds",
  source: (sourceId: string) => `/mail/sources/${id(sourceId)}`,
  sourceRules: (sourceId: string) => `/mail/sources/${id(sourceId)}/rules`,
  sourceRulesOrder: (sourceId: string) => `/mail/sources/${id(sourceId)}/rules/order`,
  /** POST — where would a message like this land? Nothing is created or sent. */
  sourcePreview: (sourceId: string) => `/mail/sources/${id(sourceId)}/preview`,
  sender: (senderId: string) => `/mail/senders/${id(senderId)}`,
  senderTest: (senderId: string) => `/mail/senders/${id(senderId)}/test`,
  rule: (ruleId: string) => `/mail/rules/${id(ruleId)}`,
  /** Signature detection: domain rules + the AI switch (one document, PUT whole). */
  signatures: "/mail/signatures",
  signaturesPreview: "/mail/signatures/preview",
} as const;

/** This plugin's query keys, all under `["mail", …]`. */
export const mailKeys = {
  sources: ["mail", "sources"] as const,
  senders: ["mail", "senders"] as const,
  kinds: ["mail", "kinds"] as const,
  rules: (sourceId: string) => ["mail", "rules", sourceId] as const,
  signatures: ["mail", "signatures"] as const,
};

/** Where mail arrives. Secrets never leave the server — `has_secret` only. */
export const mailSourcesQuery = () =>
  queryOptions({
    queryKey: mailKeys.sources,
    queryFn: ({ signal }) => api.get<MailSource[]>(MailPath.sources, { signal }),
    staleTime: 30_000,
  });

/** The relays mail goes out through. */
export const mailSendersQuery = () =>
  queryOptions({
    queryKey: mailKeys.senders,
    queryFn: ({ signal }) => api.get<MailSender[]>(MailPath.senders, { signal }),
    staleTime: 30_000,
  });

/** One source's routing chain, position-ordered top-down. */
export const mailRulesQuery = (sourceId: string) =>
  queryOptions({
    queryKey: mailKeys.rules(sourceId),
    queryFn: ({ signal }) => api.get<MailRule[]>(MailPath.sourceRules(sourceId), { signal }),
  });

/** Static per-kind catalog both dialogs share. */
export const mailKindsQuery = () =>
  queryOptions({
    queryKey: mailKeys.kinds,
    queryFn: ({ signal }) => api.get<MailKinds>(MailPath.kinds, { signal }),
    staleTime: Infinity,
  });
