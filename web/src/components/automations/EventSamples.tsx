/**
 * What this event actually carries (RADD-921).
 *
 * Every condition an automation writes against an event names a path into its
 * payload — `{{payload.changes.field}}` in a template, a dotted path in the
 * payload condition, a field name in "field changed". None of it was
 * discoverable: you wrote a path, saved, waited for the event to fire, and
 * learned from the absence of an effect that you had guessed wrong.
 *
 * The paths come from REAL recent events, not a hand-written example, because a
 * hand-written one would be a second copy of a shape defined across twenty
 * modules and would drift silently — and a payload that looks right and isn't is
 * exactly the failure this exists to prevent. The cost is stated rather than
 * hidden: an event type that has never fired here has no sample, and this says
 * so instead of showing a plausible shape nobody can trust.
 *
 * Clicking a path inserts it, because the point of showing them is to use them.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Braces, Copy } from "lucide-react";
import { copyText } from "../../lib/clipboard";
import { eventSampleQuery } from "../../lib/queries";

interface EventSamplesProps {
  eventType: string;
  /** Insert `{{payload.<path>}}` — absent when there is nowhere to put it. */
  onInsert?: (token: string) => void;
}

export function EventSamples({ eventType, onInsert }: EventSamplesProps) {
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState<{ path: string; ok: boolean } | null>(null);
  const sample = useQuery(eventSampleQuery(eventType));

  if (!eventType || sample.isError) return null;

  const data = sample.data;
  const count = data?.paths.length ?? 0;

  const copy = async (path: string) => {
    const token = `{{payload.${path}}}`;
    if (onInsert) {
      onInsert(token);
      setFeedback({ path, ok: true });
    } else {
      // Only claim it was copied if it WAS — a self-hosted instance on plain
      // http has no clipboard API, and "Copied" over a no-op is a small lie
      // that costs someone a real minute of confusion.
      setFeedback({ path, ok: await copyText(token) });
    }
    window.setTimeout(() => setFeedback(null), 1600);
  };

  return (
    <div className="rounded-[6px] border border-subtle" data-event-samples={eventType}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] uppercase tracking-wide text-fg-muted hover:text-heading cursor-pointer"
      >
        <Braces size={12} aria-hidden />
        What this event carries
        <span className="ml-auto text-fg-faint">
          {sample.isLoading ? "…" : count > 0 ? count : "none yet"}
        </span>
      </button>

      {open && (
        <div className="flex flex-col gap-1.5 border-t border-subtle p-1.5">
          {sample.isLoading && <p className="text-[11px] text-fg-muted">Reading recent events…</p>}

          {/* DECLARED shape (RADD-923) — what the event promises, from the
              plugin that emits it. Shown whether or not it has ever fired, which
              is the half sampling cannot answer. */}
          {data && (data.subjects.length > 0 || Object.keys(data.declared_schema).length > 0) && (
            <p className="text-[11px] text-fg-muted">
              Declares{" "}
              {data.subjects.map((subject) => (
                <code key={subject} className="mr-1 text-accent-text">
                  {subject}
                </code>
              ))}
              {data.subjects.length > 0 && (
                <span>— each a full ref ({"{{payload."}
                  {data.subjects[0]}.key{"}}"} and so on)</span>
              )}
            </p>
          )}

          {data && data.sampled === 0 && (
            // Honest rather than helpful-looking. A fabricated SAMPLE would be
            // worse than nothing because it would be believed — but a DECLARED
            // shape is a promise the emitter made, so it is shown above.
            <p className="text-[11px] text-fg-muted">
              No <code className="text-fg-secondary">{eventType}</code> events have been recorded on
              this instance yet, so there is nothing to sample. Real values appear once one fires.
            </p>
          )}

          {data && data.sampled > 0 && (
            <>
              <p className="text-[11px] text-fg-faint">
                From the {data.sampled} most recent — click a path to use it.
              </p>
              <ul className="flex max-h-56 flex-col gap-0.5 overflow-y-auto">
                {data.paths.map((entry) => (
                  <li key={entry.path}>
                    <button
                      type="button"
                      onClick={() => void copy(entry.path)}
                      title={onInsert ? `Insert {{payload.${entry.path}}}` : "Copy the token"}
                      className="flex w-full items-baseline gap-1.5 rounded-[4px] px-1.5 py-1 text-left hover:bg-elevated cursor-pointer"
                    >
                      <code className="shrink-0 text-[11px] text-accent-text">{entry.path}</code>
                      {entry.repeated && (
                        <span
                          title="Inside a list — a template reading it may render several values"
                          className="shrink-0 text-[9px] uppercase tracking-wide text-fg-faint"
                        >
                          many
                        </span>
                      )}
                      <span
                        className={`truncate text-[11px] ${
                          entry.examples.length > 0 ? "text-fg-secondary" : "text-fg-faint"
                        }`}
                      >
                        {/* A path with no examples is a REAL finding — the field
                            exists and has been null in everything sampled — not a
                            rendering failure, so it says which. */}
                        {entry.examples.join(" · ") || "empty in every sample"}
                      </span>
                      {feedback?.path === entry.path ? (
                        <span className="ml-auto shrink-0 text-[10px] text-fg-muted">
                          {onInsert ? "inserted" : feedback.ok ? "copied" : "select it above"}
                        </span>
                      ) : (
                        <Copy size={10} className="ml-auto shrink-0 text-fg-faint" aria-hidden />
                      )}
                    </button>
                  </li>
                ))}
              </ul>

              {data.changed_fields.length > 0 && (
                <p className="text-[11px] text-fg-muted">
                  Fields seen changing:{" "}
                  <span className="text-fg-secondary">{data.changed_fields.join(", ")}</span>
                </p>
              )}

              {data.example && (
                <details className="text-[11px]">
                  <summary className="cursor-pointer text-fg-muted hover:text-heading">
                    One whole payload
                  </summary>
                  <pre className="mt-1 max-h-48 overflow-auto rounded-[4px] bg-base p-1.5 text-[10px] text-fg-secondary">
                    {JSON.stringify(data.example, null, 2)}
                  </pre>
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
