import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "issue-types", noun: "issue types",
    meta: { entities: [Entity.project, Entity.role] },
    ...optionTransport("/issue-types/options"),
  }),
];
