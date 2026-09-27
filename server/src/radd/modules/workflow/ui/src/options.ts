import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "states", noun: "state names",
    meta: { entities: [Entity.project, Entity.role] },
    ...optionTransport("/states/options"),
  }),
];
