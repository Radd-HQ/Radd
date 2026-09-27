import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "releases", noun: "release versions",
    meta: { entities: [Entity.release, Entity.project, Entity.role] },
    ...optionTransport("/releases/options"),
  }),
];
