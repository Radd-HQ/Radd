import { optionContribution, optionTransport, Entity } from "@radd/plugin-sdk";

/** Transport and vocabulary belong to this plugin; controls are generic. */
export const optionContributions = [
  optionContribution({
    resource: "users", noun: "people", hintAfter: true, stacked: true,
    meta: { entities: [Entity.member, Entity.project, Entity.role] },
    ...optionTransport("/users/options"),
  }),
  optionContribution({
    resource: "users/directory", noun: "people",
    meta: { entities: [Entity.member, Entity.project, Entity.role] },
    ...optionTransport("/users/directory/options"),
  }),
  optionContribution({
    resource: "roles", noun: "roles",
    meta: { entities: [Entity.role, Entity.project] },
    ...optionTransport("/roles/options"),
  }),
  optionContribution({
    resource: "roles/assignable", noun: "roles",
    meta: { entities: [Entity.role, Entity.project] },
    ...optionTransport("/roles/assignable/options"),
  }),
];
