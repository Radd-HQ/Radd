import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "teams", noun: "team names",
    meta: { entities: [Entity.team, Entity.project, Entity.role, Entity.member, Entity.group] },
    ...optionTransport("/teams/options"),
  }),
  optionContribution({
    resource: "teams/directory", noun: "teams",
    meta: { entities: [Entity.team, Entity.project, Entity.role, Entity.member, Entity.group] },
    ...optionTransport("/teams/directory/options"),
  }),
];
