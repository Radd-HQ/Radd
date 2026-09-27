import { api, definePlugin, type QuerySource, Entity } from "@radd/plugin-sdk";
import type { WorkCategoryChoice } from "./lookup-contract";
const categories: QuerySource<WorkCategoryChoice[]> = {key: "timelogging.categories", meta: {entities: [Entity.workCategory, Entity.role, Entity.member, Entity.accessGrant]},
  fetch: (_args, signal) => api.get<WorkCategoryChoice[]>("/work-categories", {signal}),
};
export default definePlugin({querySources: [categories]});
