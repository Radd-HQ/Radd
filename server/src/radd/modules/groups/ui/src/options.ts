import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "groups", noun: "directory groups",
    meta: { entities: [Entity.group, Entity.project, Entity.role] },
    ...optionTransport("/groups/options"),
  }),
];
