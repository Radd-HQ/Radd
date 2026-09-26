import { definePlugin, SlotId, type Item, type Project } from "@radd/plugin-sdk";
import { TRANSITION_RULE_SLOT, type TransitionRuleEditorProps } from "@radd-plugin-ui/workflow/transition-rule-contract";
import { ApprovalsCard } from "./ApprovalsCard";
import { ApprovalRuleEditor, REQUIRE_APPROVAL } from "./ApprovalRuleEditor";
import { AwaitingApproval, AWAITING_WIDGET } from "./AwaitingApproval";

export default definePlugin({
  contributions: [
    {
      id: "approvals",
      slot: SlotId.issuePanelSection,
      order: 35,
      render: (props) => {
        const { item, project } = props as { item: Item; project: Project };
        return <ApprovalsCard item={item} project={project} />;
      },
    },
    {
      id: "require-approval-rule",
      slot: TRANSITION_RULE_SLOT,
      // The check this editor owns — the host reads it to tell a served rule from an orphan.
      match: REQUIRE_APPROVAL,
      toggleable: false,
      label: "Require approval (transition rule)",
      render: (props) => <ApprovalRuleEditor {...(props as unknown as TransitionRuleEditorProps)} />,
    },
    {
      id: "awaiting-approval",
      slot: SlotId.dashboardWidget,
      match: AWAITING_WIDGET,
      label: "Awaiting my approval (My Work widget)",
      render: () => <AwaitingApproval />,
    },
  ],
});
