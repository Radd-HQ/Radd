import { optionContribution, optionTransport } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "teams", noun: "team names",
    meta: { entities: ["team", "project", "role", "member", "group"] },
    ...optionTransport("/teams/options"),
  }),
  optionContribution({
    resource: "teams/directory", noun: "teams",
    meta: { entities: ["team", "project", "role", "member", "group"] },
    ...optionTransport("/teams/directory/options"),
  }),
];
