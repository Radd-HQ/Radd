import { api, type CommandSource } from "@radd/plugin-sdk";
import type { RunnableRule } from "./types";
export const manualCommands: CommandSource = {
  id: "manual", entityType: "item", meta: {entities: ["automation", "role", "member", "accessGrant"]},
  list: async (_context, signal) => (await api.get<RunnableRule[]>("/automations/runnable", {signal})).map(rule => ({
    id: rule.id, label: rule.name, hint: "automation", keywords: "run automation custom action",
  })),
  execute: (id, context, signal) => api.post<void>(`/automations/${encodeURIComponent(id)}/run`, {item_id: context.entityId}, {signal}),
};
