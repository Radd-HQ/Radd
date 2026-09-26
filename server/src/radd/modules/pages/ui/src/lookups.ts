import { api, type QuerySource } from "@radd/plugin-sdk";
import type { PageChoices } from "./lookup-contract";
export const searchSource: QuerySource<PageChoices> = {key: "pages.search", meta: {entities: ["page", "docSpace", "role", "accessGrant", "member"]},
  fetch: (args, signal) => api.get<PageChoices>("/pages/search", {signal, query: {q: String(args.q ?? ""), limit: "20"}}),
};
