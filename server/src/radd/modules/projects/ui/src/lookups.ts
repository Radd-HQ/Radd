import { api, type QuerySource } from "@radd/plugin-sdk";
import type { FirstProject } from "./lookup-contract";
export const firstProjectSource: QuerySource<FirstProject[]> = {key: "projects.first", meta: {entities: ["project", "role", "accessGrant", "member"]},
  fetch: (_args, signal) => api.get<FirstProject[]>("/projects", {signal, query: {limit: "1"}}),
};
