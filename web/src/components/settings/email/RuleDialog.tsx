import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../../../lib/api";
import { apiMailRulePath, apiMailSourceRulesPath } from "../../../lib/constants";
import { projectsQuery } from "../../../lib/queries";
import {
  MailRuleType,
  type MailRule,
  type MailRuleTypeValue,
  type MailSource,
} from "../../../lib/types";
import { Button } from "../../Button";
import { ErrorText } from "../../ErrorText";
import { IconButton } from "../../IconButton";
import { Modal } from "../../Modal";
import { Select } from "../../Select";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { TokenMultiSelect } from "../../TokenMultiSelect";

/** What each rule kind matches on, in the operator's words. */
export const RULE_LABELS: Record<MailRuleTypeValue, string> = {
  [MailRuleType.recipient]: "Delivered to (alias)",
  [MailRuleType.sender]: "From address or domain",
  [MailRuleType.subject]: "Subject contains",
  [MailRuleType.llm]: "AI — decide from the content",
};

const VALUE_LABELS: Record<MailRuleTypeValue, string> = {
  [MailRuleType.recipient]: "Addresses (aliases)",
  [MailRuleType.sender]: "Addresses or @domains",
  [MailRuleType.subject]: "Subject contains",
  [MailRuleType.llm]: "",
};

const VALUE_PLACEHOLDERS: Record<MailRuleTypeValue, string> = {
  [MailRuleType.recipient]: "pipeline@radd-hq.com — type and press Enter",
  [MailRuleType.sender]: "@vip-customer.com — type and press Enter",
  [MailRuleType.subject]: "[URGENT] — type and press Enter",
  [MailRuleType.llm]: "",
};

/** One step of a source's routing chain. */
export function RuleDialog({
  source,
  rule,
  onClose,
}: {
  source: MailSource;
  rule: MailRule | null;
  onClose: () => void;
}) {
  const projects = useQuery(projectsQuery());
  const [name, setName] = useState(rule?.name ?? "");
  const [type, setType] = useState<MailRuleTypeValue>(rule?.rule_type ?? MailRuleType.recipient);
  const [projectId, setProjectId] = useState(rule?.project_id ?? "");
  const [values, setValues] = useState<string[]>(() => {
    const c = (rule?.config ?? {}) as Record<string, string[]>;
    return c.addresses ?? c.patterns ?? c.contains ?? [];
  });
  const [prompt, setPrompt] = useState(
    (rule?.config as { prompt?: string } | undefined)?.prompt ??
      "Classify this support email into one of the given categories.",
  );
  const [answers, setAnswers] = useState<{ answer: string; project_id: string }[]>(
    (rule?.config as { answers?: { answer: string; project_id: string }[] } | undefined)?.answers ??
      [],
  );

  const projectOptions = (projects.data ?? []).map((p) => ({ value: p.id, label: p.key }));

  const configFor = (): Record<string, unknown> => {
    if (type === MailRuleType.recipient) return { addresses: values };
    if (type === MailRuleType.sender) return { patterns: values };
    if (type === MailRuleType.subject) return { contains: values };
    return { prompt, answers: answers.filter((a) => a.answer && a.project_id) };
  };

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        rule_type: type,
        enabled: rule?.enabled ?? true,
        config: configFor(),
        project_id: type === MailRuleType.llm ? null : projectId || null,
      };
      return rule
        ? api.patch(apiMailRulePath(rule.id), body)
        : api.post(apiMailSourceRulesPath(source.id), body);
    },
    onSuccess: onClose,
  });

  return (
    <Modal title={rule ? `Edit ${rule.name}` : "New routing rule"} onClose={onClose}>
      <div className="flex flex-col gap-3">
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField
          label="Match on"
          value={type}
          onChange={(e) => setType(e.target.value as MailRuleTypeValue)}
        >
          {Object.entries(RULE_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>

        {type === MailRuleType.llm ? (
          <>
            <TextField
              label="Prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              hint={
                "The model picks from the categories below and can never invent a project. " +
                'It is always offered one extra answer — "None of these" — so off-topic mail ' +
                "falls to the source default as a decision rather than a failure. If AI is " +
                "off or slow, the chain simply continues to the next rule."
              }
            />
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-fg-secondary">Categories → project</span>
              {answers.map((a, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    value={a.answer}
                    onChange={(e) =>
                      setAnswers((prev) =>
                        prev.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)),
                      )
                    }
                    placeholder="build failure"
                    aria-label="Category"
                    className="h-8 flex-1 rounded-md border border-strong bg-surface px-2 text-[13px] text-heading focus:outline-2 focus:outline-focus"
                  />
                  <Select
                    value={a.project_id}
                    onChange={(value) =>
                      setAnswers((prev) =>
                        prev.map((x, j) => (j === i ? { ...x, project_id: value } : x)),
                      )
                    }
                    options={projectOptions}
                    placeholder="— project —"
                    aria-label="Category project"
                  />
                  <IconButton
                    danger
                    aria-label="Remove category"
                    onClick={() => setAnswers((prev) => prev.filter((_, j) => j !== i))}
                  >
                    <Trash2 size={13} />
                  </IconButton>
                </div>
              ))}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setAnswers((p) => [...p, { answer: "", project_id: "" }])}
              >
                <Plus size={12} aria-hidden />
                Add category
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-secondary">{VALUE_LABELS[type]}</span>
              <TokenMultiSelect
                value={values}
                onChange={setValues}
                options={[]}
                allowCreate
                placeholder={VALUE_PLACEHOLDERS[type]}
                ariaLabel="Rule values"
              />
            </div>
            <SelectField
              label="Opens in project"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">— none —</option>
              {(projects.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.key} · {p.name}
                </option>
              ))}
            </SelectField>
          </>
        )}

        {save.isError && <ErrorText error={save.error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : "Save rule"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
