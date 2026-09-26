import { api, definePlugin, type QuerySource } from "@radd/plugin-sdk";
import type { WorkCategoryChoice } from "./lookup-contract";
const categories: QuerySource<WorkCategoryChoice[]> = {key: "timelogging.categories", meta: {entities: ["workCategory", "role", "member", "accessGrant"]},
  fetch: (_args, signal) => api.get<WorkCategoryChoice[]>("/work-categories", {signal}),
};
export default definePlugin({querySources: [categories]});
