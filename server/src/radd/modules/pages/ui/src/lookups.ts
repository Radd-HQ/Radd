import { api, type QuerySource, Entity } from "@radd/plugin-sdk";
import type { PageChoices } from "./lookup-contract";
export const searchSource: QuerySource<PageChoices> = {key: "pages.search", meta: {entities: [Entity.page, Entity.docSpace, Entity.role, Entity.accessGrant, Entity.member]},
  fetch: (args, signal) => api.get<PageChoices>("/pages/search", {signal, query: {q: String(args.q ?? ""), limit: "20"}}),
};
