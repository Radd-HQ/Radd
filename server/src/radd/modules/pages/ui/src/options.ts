import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "page-spaces", noun: "wiki spaces",
    meta: { entities: [Entity.docSpace, Entity.project, Entity.role] },
    ...optionTransport("/page-spaces/options"),
  }),
];
