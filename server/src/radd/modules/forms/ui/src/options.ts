import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "forms", noun: "intake forms",
    meta: { entities: [Entity.form, Entity.project, Entity.role] },
    ...optionTransport("/forms/options"),
  }),
];
