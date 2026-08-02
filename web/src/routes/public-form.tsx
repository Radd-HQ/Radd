import { useState, type FormEvent } from "react";
import { useParams } from "@tanstack/react-router";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList } from "lucide-react";
import { api, customFieldErrors, errorMessage } from "../lib/api";
import {
  DEFLECT_DEBOUNCE_MS,
  DEFLECT_MIN_QUERY_CHARS,
  apiPublicFormDeflectPath,
  apiPublicFormPath,
} from "../lib/constants";
import { useDebounced } from "../lib/hooks";
import { publicFormQuery } from "../lib/queries";
import {
  type CustomFields,
  type PublicDeflectResponse,
  type PublicForm,
  type PublicFormSubmit,
  type PublicSubmitResult,
} from "../lib/types";
import {
  FormDescriptionArea,
  PublicFormFieldList,
  collectValues,
} from "../components/forms/PublicFormFields";
import { DeflectDocsSection } from "../components/items/DeflectionPanel";
import { Button } from "../components/Button";
import { RaddTile } from "../components/RaddMark";
import { Spinner } from "../components/Spinner";
import { TextField } from "../components/TextField";

/**
 * PUBLIC tokened form page (spec 62) — route `/public/forms/$token`, root-level
 * and OUTSIDE the auth gate (like /login): anyone with the link can file a
 * request. Field definitions arrive inlined in the render payload (the registry
 * needs a login), email/name identify the requester (registered email → they
 * become the reporter; anything else becomes the item's mail contact and gets
 * the ack + reply emails), and the success screen shows the created issue key —
 * a plain key, not a link, since the visitor can't open the tracker.
 *
 * The description editor mounts in `anonymous` mode (spec 106): formatting
 * only — no AI probes, no @/# lookups; every one of those needs a session.
 */
export function PublicFormPage() {
  const { token = "" } = useParams({ strict: false });
  const form = useQuery(publicFormQuery(token));

  return (
    <main className="flex min-h-screen flex-col items-center bg-base px-4 py-10">
      {/* The brand block keeps its own measure — when the deflection aside
          widens the row below, the card shifts left of it (same "the reading
          measure shifts" behavior as the issue page's results pane). */}
      <div className="mb-6 flex w-full max-w-xl items-center gap-2.5">
        <RaddTile className="size-8 rounded-lg" />
        <div>
          <h1 className="text-base font-semibold text-heading">Radd</h1>
          <p className="text-xs text-fg-muted">Submit a request</p>
        </div>
      </div>
      {form.isPending ? (
        <Spinner label="Loading form…" />
      ) : form.isError ? (
        <p className="w-full max-w-xl text-sm text-fg-secondary">
          This form link isn't available: {errorMessage(form.error)}
        </p>
      ) : (
        <PublicSubmitForm token={token} form={form.data} />
      )}
    </main>
  );
}

/**
 * KB deflection for the anonymous visitor (spec 74; semantic-fused server-side
 * when available — spec 106): while they type a title, surface PUBLIC wiki
 * pages that may already answer it via the tokened
 * `/public/forms/{token}/deflect` endpoint (docs only — resolved issues stay
 * internal). Same debounce/gating as the authed panels; links open the public
 * /kb routes in a new tab so the half-typed form survives. Mounted twice
 * (inline narrow / aside wide) — the query dedupes on its key.
 */
function PublicDeflectionPanel({ token, query }: { token: string; query: string }) {
  const debounced = useDebounced(query, DEFLECT_DEBOUNCE_MS);
  const deflect = useQuery({
    queryKey: ["public-kb", "form-deflect", token, debounced],
    queryFn: () =>
      api.get<PublicDeflectResponse>(apiPublicFormDeflectPath(token), {
        query: { q: debounced },
      }),
    placeholderData: keepPreviousData,
    retry: false,
    enabled: debounced.trim().length >= DEFLECT_MIN_QUERY_CHARS,
  });
  const docs = deflect.data?.docs ?? [];
  // Gate on the LIVE query too — kept-previous data must not outlive a cleared title.
  if (query.trim().length < DEFLECT_MIN_QUERY_CHARS || docs.length === 0) return null;

  return (
    <div className="flex flex-col gap-1 rounded-md border border-subtle bg-surface/40 p-2.5">
      <DeflectDocsSection docs={docs} kb />
    </div>
  );
}

function PublicSubmitForm({ token, form }: { token: string; form: PublicForm }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [values, setValues] = useState<CustomFields>({});
  const [created, setCreated] = useState<PublicSubmitResult | null>(null);

  const submit = useMutation({
    mutationFn: () => {
      const body: PublicFormSubmit = {
        title: title.trim(),
        description: form.description_enabled ? description : undefined,
        values: collectValues(values),
        email: email.trim(),
        name: name.trim() || undefined,
      };
      return api.post<PublicSubmitResult>(apiPublicFormPath(token), body);
    },
    onSuccess: (result) => setCreated(result),
  });

  const fieldErrors = submit.isError ? customFieldErrors(submit.error) : {};
  const generalError =
    submit.isError && Object.keys(fieldErrors).length === 0 ? errorMessage(submit.error) : null;

  const descriptionMissing =
    form.description_enabled && form.description_required && !description.trim();
  const canSubmit = title.trim() !== "" && email.trim() !== "" && !descriptionMissing;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSubmit) submit.mutate();
  };

  const reset = () => {
    setTitle("");
    setDescription("");
    setValues({});
    setCreated(null);
    submit.reset();
  };

  // The deflection panel rides BESIDE the card on wide screens — this page is
  // standalone (no collapsible sidebar), so viewport breakpoints are honest.
  return (
    <div className="flex w-full flex-col items-center gap-6 lg:flex-row lg:items-start lg:justify-center">
      <div className="flex w-full max-w-xl flex-col gap-6 rounded-xl border border-subtle bg-surface/40 p-6">
        <header className="flex flex-col gap-2 border-b border-subtle pb-4">
          <div className="flex items-center gap-2 text-accent-text">
            <ClipboardList size={18} aria-hidden />
            <span className="text-[11px] font-medium uppercase tracking-wide">Request form</span>
          </div>
          <h2 className="text-xl font-semibold text-heading">{form.name}</h2>
          {form.description && <p className="text-sm text-fg-secondary">{form.description}</p>}
        </header>

        {created ? (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
            <p className="flex items-center gap-2 text-sm text-emerald-300">
              <CheckCircle2 size={16} aria-hidden />
              Submitted — your request is tracked as{" "}
              <span className="font-mono font-semibold text-emerald-200">{created.key}</span>
            </p>
            <p className="text-[13px] text-fg-secondary">{created.title}</p>
            <p className="text-xs text-fg-muted">
              We'll follow up at {email.trim()} — replies to those emails reach the ticket.
            </p>
            <Button variant="ghost" onClick={reset}>
              Submit another request
            </Button>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="flex flex-col gap-5">
            <TextField
              label={`${form.title_prompt} *`}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Short summary"
              maxLength={500}
              required
              error={fieldErrors.title}
            />

            {/* Inline on narrow screens only — the aside takes over when it
                fits beside the card. */}
            <div className="lg:hidden">
              <PublicDeflectionPanel token={token} query={title} />
            </div>

            {form.description_enabled && (
              <FormDescriptionArea
                prompt={form.description_prompt}
                required={form.description_required}
                value={description}
                error={fieldErrors.description}
                placeholder="Describe the issue — steps, context, what you expected"
                onChange={setDescription}
                anonymous
              />
            )}

            <PublicFormFieldList
              fields={form.fields}
              values={values}
              errors={fieldErrors}
              onChange={(key, value) =>
                setValues((previous) => ({ ...previous, [key]: value }))
              }
            />

            <div className="grid grid-cols-2 gap-3 border-t border-subtle pt-4">
              <TextField
                label="Your email *"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                maxLength={320}
                required
                hint="Updates about this request go here"
              />
              <TextField
                label="Your name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Optional"
                maxLength={200}
              />
            </div>

            {generalError && <p className="text-sm text-red-400">{generalError}</p>}

            <div className="flex justify-end">
              <Button type="submit" disabled={!canSubmit || submit.isPending}>
                {submit.isPending ? "Submitting…" : "Submit request"}
              </Button>
            </div>
          </form>
        )}
      </div>

      {!created && (
        <div className="hidden w-80 shrink-0 lg:sticky lg:top-10 lg:block">
          <PublicDeflectionPanel token={token} query={title} />
        </div>
      )}
    </div>
  );
}
