import { Button, Select, TextField, TokenList, SchemaForm, tokens } from "@radd/plugin-sdk";
import type { InspectorProps } from "./index";

type Params = Record<string, unknown>;

const note = { fontSize: 12, color: tokens.textMuted, margin: 0 } as const;
const heading = {
  fontSize: 11, fontWeight: 500, letterSpacing: "0.04em", textTransform: "uppercase", color: tokens.textMuted,
} as const;
const column = { display: "flex", flexDirection: "column", gap: 8 } as const;

/** What an AI node may be shown of the issue — the same four toggles for classify
 *  and validate; `generate` gets them from its schema. */
const SECTIONS = [
  { key: "fields", label: "Fields — type, state, priority, assignee, labels, custom fields", on: true },
  { key: "description", label: "Description (in full)", on: true },
  { key: "comments", label: "Comments (all of them)", on: false },
  { key: "worklogs", label: "Logged time", on: false },
];

/** `ai.classify` — a question and the answers it may choose between; each answer
 *  becomes a port (the server says so through the shape endpoint). */
export function ClassifyInspector({ params, onChange }: InspectorProps) {
  const include = (params.include as Record<string, boolean>) ?? {};
  return (
    <div style={column}>
      <TextField
        label="Question"
        value={String(params.prompt ?? "")}
        onChange={(event) => onChange({ ...params, prompt: event.target.value })}
        placeholder="Is this a bug report, a feature request, or a question?"
        hint="Asked once per run, with the issue summaries appended."
      />
      <span style={heading}>Possible answers</span>
      <TokenList
        value={(params.answers as string[]) ?? []}
        onChange={(answers) => onChange({ ...params, answers })}
        placeholder="Add an answer…"
        ariaLabel="Possible answers"
      />
      <p style={note}>
        Each answer becomes an output port. The model is constrained to these, so it cannot invent a
        branch — and an <strong>unavailable</strong> port catches the provider being down.
      </p>
      <span style={heading}>What the model sees</span>
      {SECTIONS.map((section) => (
        <label key={section.key} style={{ display: "flex", gap: 8, fontSize: 13, color: tokens.text, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={include[section.key] ?? section.on}
            onChange={(event) => onChange({ ...params, include: { ...include, [section.key]: event.target.checked } })}
          />
          <span>{section.label}</span>
        </label>
      ))}
      <p style={note}>
        Sent to your configured AI provider, read as the automation&rsquo;s identity. Issues are sent whole;
        past the prompt budget (RADD_AI_AUTOMATION_CONTEXT_CHARS) later issues are left out and the prompt
        says how many.
      </p>
    </div>
  );
}

interface GenerateField {
  name: string;
  kind: string;
  choices?: string[];
  description?: string;
}

const MAX_FIELDS = 8;
const ALWAYS_PRODUCED = "text";
const OUTPUT_NAME_RE = /^[a-z][a-z0-9_]{0,29}$/;

function fieldsOf(params: Params): GenerateField[] {
  const raw = params.fields;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    .map((entry) => ({
      name: String(entry.name ?? ""),
      kind: String(entry.kind ?? "text"),
      choices: Array.isArray(entry.choices) ? entry.choices.map(String) : [],
      description: String(entry.description ?? ""),
    }));
}

function nameError(name: string, fields: GenerateField[], index: number): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  if (!OUTPUT_NAME_RE.test(trimmed)) return "Lowercase letters, digits and underscores, starting with a letter.";
  if (trimmed === ALWAYS_PRODUCED) return "This node always produces {{….text}}.";
  return fields.some((field, at) => at !== index && field.name.trim() === trimmed) ? "Already used by another value." : "";
}

/** `ai.generate` — its central param is an array of objects whose shape varies per
 *  row, which a generated form cannot render; the prompt and include toggles come
 *  from the node's own schema through the host's form. */
export function GenerateInspector({ params, onChange, schema }: InspectorProps) {
  const fields = fieldsOf(params);
  const setFields = (next: GenerateField[]) => onChange({ ...params, fields: next });
  const patch = (index: number, changes: Partial<GenerateField>) =>
    setFields(fields.map((field, at) => (at === index ? { ...field, ...changes } : field)));
  const properties = { ...(((schema ?? {}).properties ?? {}) as Record<string, unknown>) };
  delete properties.fields;
  return (
    <div style={{ ...column, gap: 12 }}>
      {schema && (
        <SchemaForm
          schema={{ ...schema, properties }}
          params={params}
          onChange={(next) => onChange({ ...next, fields: params.fields ?? [] })}
        />
      )}
      <div style={column} data-generate-fields>
        <span style={heading}>
          Values to produce ({fields.length}/{MAX_FIELDS})
        </span>
        <p style={note}>
          Each becomes a token downstream. A field with a list of allowed values is enforced by the model&rsquo;s
          own decoding, so it cannot answer with anything else.
        </p>
        {fields.map((field, index) => (
          <div
            key={index}
            data-generate-field={index}
            style={{ ...column, border: `1px solid ${tokens.border}`, borderRadius: 8, padding: 8 }}
          >
            <TextField
              label="Name"
              value={field.name}
              placeholder="priority"
              error={nameError(field.name, fields, index) || undefined}
              onChange={(event) => patch(index, { name: event.target.value })}
            />
            <Select label="Kind" value={field.kind} onChange={(event) => patch(index, { kind: event.target.value })}>
              <option value="text">Text</option>
              <option value="enum">One of…</option>
            </Select>
            {field.kind === "enum" && (
              <>
                <span style={heading}>Allowed values</span>
                <TokenList
                  value={field.choices ?? []}
                  onChange={(choices) => patch(index, { choices })}
                  placeholder="Add a value…"
                  ariaLabel="Allowed values"
                />
              </>
            )}
            <Button variant="danger" small onClick={() => setFields(fields.filter((_, at) => at !== index))}>
              Remove
            </Button>
          </div>
        ))}
        <div>
          <Button
            variant="ghost"
            small
            disabled={fields.length >= MAX_FIELDS}
            onClick={() => setFields([...fields, { name: "", kind: "text", choices: [], description: "" }])}
          >
            Add a value
          </Button>
        </div>
      </div>
    </div>
  );
}
