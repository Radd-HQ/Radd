import { api, type QuerySource } from "@radd/plugin-sdk";
import type { ItemChoice } from "./lookup-contract";
export const searchSource: QuerySource<ItemChoice[]> = {key: "items.link-search", meta: {entities: ["item", "project", "role", "accessGrant", "member"]},
  fetch: (args, signal) => api.get<ItemChoice[]>("/items/link-search", {signal, query: {project_id: String(args.projectId ?? ""), q: String(args.q ?? "")}}),
};
