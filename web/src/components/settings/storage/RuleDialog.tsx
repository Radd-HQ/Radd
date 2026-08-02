import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { api, errorMessage } from "../../../lib/api";
import { ApiPath, apiStorageRulePath } from "../../../lib/constants";
import { queryKeys } from "../../../lib/queries";
import {
  StorageRuleType,
  type CidrRange,
  type LlmAnswer,
  type StorageHostRead,
  type StorageRuleConfig,
  type StorageRuleCreatePayload,
  type StorageRuleRead,
  type StorageRuleTypeValue,
  type StorageRuleUpdatePayload,
} from "../../../lib/types";
import { Button } from "../../Button";
import { Modal } from "../../Modal";
import { Select } from "../../Select";
import { SelectField } from "../../SelectField";
import { TextField } from "../../TextField";
import { TokenMultiSelect, type TokenOption } from "../../TokenMultiSelect";

/** Backend defaults mirrored for the form's initial state (LlmConfig). */
const LLM_DEFAULT_PREFIXES = ["image/"];
const LLM_DEFAULT_TIMEOUT_SECONDS = 10;
const LLM_MIN_ANSWERS = 2;

/** Common content-type prefixes offered in the LLM rule's token picker. */
const PREFIX_OPTIONS: TokenOption[] = [
  { value: "image/", label: "image/" },
  { value: "video/", label: "video/" },
  { value: "audio/", label: "audio/" },
  { value: "application/pdf", label: "application/pdf" },
];

/** Row input matching TextField's styling, for the repeatable builders where a
 * label per row would be noise (the FormEditor idiom). */
const rowInputClasses =
  "h-8 min-w-0 flex-1 rounded-md border border-subtle bg-surface px-2.5 text-[13px] " +
  "text-heading placeholder:text-fg-faint focus:border-accent focus:outline-none " +
  "focus:ring-2 focus:ring-accent/30";

/**
 * Create/edit one routing rule (spec 102). The type is immutable after
 * creation (the update schema has no rule_type); config shape is per-type and
 * the server 422s invalid combinations — its detail surfaces inline.
 */
export function RuleDialog({
  existing,
  hosts,
  onClose,
}: {
  existing: StorageRuleRead | null;
  hosts: StorageHostRead[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(existing?.name ?? "");
  const [ruleType, setRuleType] = useState<StorageRuleTypeValue>(
    existing?.rule_type ?? StorageRuleType.userChoice,
  );
  const [ranges, setRanges] = useState<CidrRange[]>(
    existing?.config.ranges ?? [{ cidr: "", host_id: "" }],
  );
  const [prompt, setPrompt] = useState(existing?.config.prompt ?? "");
  const [answers, setAnswers] = useState<LlmAnswer[]>(
    existing?.config.answers ??
      Array.from({ length: LLM_MIN_ANSWERS }, () => ({ answer: "", host_id: "" })),
  );
  const [prefixes, setPrefixes] = useState<string[]>(
    existing?.config.content_type_prefixes ?? LLM_DEFAULT_PREFIXES,
  );
  const [timeout, setTimeoutSeconds] = useState(
    String(existing?.config.timeout_seconds ?? LLM_DEFAULT_TIMEOUT_SECONDS),
  );

  const hostOptions = hosts.map((host) => ({ value: host.id, label: host.name }));

  const save = useMutation({
    mutationFn: (body: StorageRuleCreatePayload | StorageRuleUpdatePayload) =>
      existing
        ? api.patch<StorageRuleRead>(apiStorageRulePath(existing.id), body)
        : api.post<StorageRuleRead>(ApiPath.storageRules, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageRules });
      // A user-choice rule appearing/vanishing changes whether uploads prompt.
      void queryClient.invalidateQueries({ queryKey: queryKeys.storageUploadContext });
      onClose();
    },
  });

  const config: StorageRuleConfig =
    ruleType === StorageRuleType.cidr
      ? { ranges }
      : ruleType === StorageRuleType.llm
        ? {
            prompt,
            answers,
            content_type_prefixes: prefixes,
            timeout_seconds: Number(timeout),
          }
        : {};

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    save.mutate(
      existing
        ? ({ name: name.trim(), config } satisfies StorageRuleUpdatePayload)
        : ({ name: name.trim(), rule_type: ruleType, config } satisfies StorageRuleCreatePayload),
    );
  };

  return (
    <Modal title={existing ? "Edit rule" : "Add routing rule"} onClose={onClose} wide>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <TextField
          label="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Renders stay on-prem"
          maxLength={200}
          required
        />
        <SelectField
          label="Type"
          value={ruleType}
          onChange={(event) => setRuleType(event.target.value as StorageRuleTypeValue)}
          disabled={Boolean(existing)}
          title={existing ? "The rule type is fixed after creation" : undefined}
          hint={existing ? "Fixed after creation — add a new rule to change type." : undefined}
        >
          <option value={StorageRuleType.userChoice}>Ask the uploader</option>
          <option value={StorageRuleType.cidr}>Uploader network (CIDR)</option>
          <option value={StorageRuleType.llm}>AI classifier</option>
        </SelectField>

        {ruleType === StorageRuleType.userChoice && (
          <p className="rounded-md border border-subtle bg-elevated/50 px-3 py-2 text-xs text-fg-muted">
            Uploaders are asked to pick among the hosts flagged user-selectable. Uploads with no
            answer (API clients, importers) fall through to the next rule.
          </p>
        )}

        {ruleType === StorageRuleType.cidr && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-fg-secondary">Ranges</span>
            <p className="text-xs text-fg-muted">
              The first range containing the uploader&rsquo;s address picks the host; no match
              falls through.
            </p>
            {ranges.map((range, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  value={range.cidr}
                  onChange={(event) =>
                    setRanges((current) =>
                      current.map((row, i) =>
                        i === index ? { ...row, cidr: event.target.value } : row,
                      ),
                    )
                  }
                  placeholder="10.20.0.0/16"
                  aria-label={`CIDR range ${index + 1}`}
                  className={rowInputClasses}
                />
                <Select
                  value={range.host_id}
                  onChange={(hostId) =>
                    setRanges((current) =>
                      current.map((row, i) => (i === index ? { ...row, host_id: hostId } : row)),
                    )
                  }
                  options={hostOptions}
                  placeholder="Host…"
                  aria-label={`Host for range ${index + 1}`}
                  className="w-44 shrink-0"
                />
                <button
                  type="button"
                  onClick={() =>
                    setRanges((current) => current.filter((_, i) => i !== index))
                  }
                  disabled={ranges.length <= 1}
                  aria-label={`Remove range ${index + 1}`}
                  className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-40 disabled:pointer-events-none"
                >
                  <X size={13} aria-hidden />
                </button>
              </div>
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={() => setRanges((current) => [...current, { cidr: "", host_id: "" }])}
            >
              <Plus size={13} aria-hidden />
              Add range
            </Button>
          </div>
        )}

        {ruleType === StorageRuleType.llm && (
          <>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-fg-secondary">Prompt</label>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={3}
                required
                placeholder="Is this a production render frame, or an ordinary screenshot/document?"
                className="rounded-md border border-strong bg-surface px-2.5 py-2 text-[13px] text-heading placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
              />
              <p className="text-xs text-fg-muted">
                The model must answer with one of the mapped answers below — it cannot invent
                another, and any failure falls through to the next rule.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-secondary">Answers</span>
              {answers.map((answer, index) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    value={answer.answer}
                    onChange={(event) =>
                      setAnswers((current) =>
                        current.map((row, i) =>
                          i === index ? { ...row, answer: event.target.value } : row,
                        ),
                      )
                    }
                    placeholder={index === 0 ? "render frame" : "something else"}
                    maxLength={100}
                    aria-label={`Answer ${index + 1}`}
                    className={rowInputClasses}
                  />
                  <Select
                    value={answer.host_id}
                    onChange={(hostId) =>
                      setAnswers((current) =>
                        current.map((row, i) =>
                          i === index ? { ...row, host_id: hostId } : row,
                        ),
                      )
                    }
                    options={hostOptions}
                    placeholder="Host…"
                    aria-label={`Host for answer ${index + 1}`}
                    className="w-44 shrink-0"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setAnswers((current) => current.filter((_, i) => i !== index))
                    }
                    disabled={answers.length <= LLM_MIN_ANSWERS}
                    aria-label={`Remove answer ${index + 1}`}
                    className="rounded p-1 text-fg-faint hover:bg-elevated hover:text-red-400 cursor-pointer disabled:opacity-40 disabled:pointer-events-none"
                  >
                    <X size={13} aria-hidden />
                  </button>
                </div>
              ))}
              <Button
                variant="ghost"
                size="sm"
                className="self-start"
                onClick={() =>
                  setAnswers((current) => [...current, { answer: "", host_id: "" }])
                }
              >
                <Plus size={13} aria-hidden />
                Add answer
              </Button>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-fg-secondary">
                Content-type prefixes
              </span>
              <TokenMultiSelect
                value={prefixes}
                onChange={setPrefixes}
                options={PREFIX_OPTIONS}
                allowCreate
                placeholder="image/…"
                ariaLabel="Content-type prefixes"
              />
              <p className="text-xs text-fg-muted">
                Only uploads whose content type starts with one of these are classified; the
                rest fall through.
              </p>
            </div>
            <TextField
              label="Timeout (seconds)"
              type="number"
              min={1}
              max={120}
              value={timeout}
              onChange={(event) => setTimeoutSeconds(event.target.value)}
              hint="A slow model must never stall an upload — past this, the rule falls through."
            />
          </>
        )}

        <div className="mt-1 flex items-center justify-end gap-2">
          {save.isError && (
            <span className="mr-auto text-xs text-red-400">{errorMessage(save.error)}</span>
          )}
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending || !name.trim()}>
            {save.isPending ? "Saving…" : existing ? "Save changes" : "Add rule"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
