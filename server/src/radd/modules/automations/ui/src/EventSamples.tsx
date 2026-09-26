/**
 * What this event carries: paths from REAL recent events (a hand-written example would drift from a shape
 * defined across many modules) plus what the event DECLARES. An event never fired here says so instead of
 * showing an invented shape. Clicking a path copies its token.
 */
import { useEffect, useRef, useState } from "react";
import { ErrorText, Button } from "@radd/plugin-sdk";
import { useAutomationQuery as useQuery } from "./query-lifetime";

import { Braces, Copy } from "lucide-react";
import { copyText } from "@radd/plugin-sdk";
import { eventSampleQuery } from "./queries";
import { isSentinelTrigger } from "./meta";

type Feedback = { path: string; ok: boolean } | null;

/** One path; a click copies its token. */
function PathRow({ path, many = false, detail, faint, icon, feedback, onCopy }: {
  path: string;
  many?: boolean;
  detail: string;
  faint: boolean;
  icon: boolean;
  feedback: Feedback;
  onCopy: (path: string) => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onCopy(path)}
        title="Copy the token"
        className="flex w-full items-baseline gap-1.5 rounded-[4px] px-1.5 py-1 text-left hover:bg-elevated cursor-pointer"
      >
        <code className="shrink-0 text-[11px] text-accent-text">{path}</code>
        {many && (
          <span
            title="Inside a list — a template reading it may render several values"
            className="shrink-0 text-[9px] uppercase tracking-wide text-fg-faint"
          >
            many
          </span>
        )}
        <span className={`truncate text-[11px] ${faint ? "text-fg-faint" : "text-fg-secondary"}`}>{detail}</span>
        {feedback?.path === path ? (
          <span className="ml-auto shrink-0 text-[10px] text-fg-muted">{feedback.ok ? "copied" : "select it above"}</span>
        ) : icon ? (
          <Copy size={10} className="ml-auto shrink-0 text-fg-faint" aria-hidden />
        ) : null}
      </button>
    </li>
  );
}

export function EventSamples({ eventType }: { eventType: string }) {
  const live = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {live.current = true; return () => {live.current = false; clearTimeout(timer.current);};}, []);
  const [open, setOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const sample = useQuery(eventSampleQuery(eventType));

  if (!eventType || isSentinelTrigger(eventType)) return null;
  if (sample.isError) return <div role="alert"><ErrorText error={sample.error} /><Button variant="ghost" size="sm" onClick={() => void sample.refetch()}>Retry event samples</Button></div>;

  const data = sample.data;
  const observed = new Set(data?.paths.map((entry) => entry.path) ?? []);
  const declared = (data?.declared_paths ?? []).filter((entry) => !observed.has(entry.path));
  const count = observed.size + declared.length;

  const copy = async (path: string) => {
    // Only claim it was copied if it WAS — plain-http instances have no clipboard API.
    const ok = await copyText(`{{payload.${path}}}`);
    if (!live.current) return;
    setFeedback({ path, ok });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setFeedback(null), 1600);
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

          {/* RADD-1331: what the event DECLARES, usable before it has ever fired.
              Subject refs carry real values from a ref of that type seen here;
              schema paths carry none — nothing is invented. */}
          {declared.length > 0 && (
            <>
              <p className="text-[11px] text-fg-faint">Declared by the event — click a path to use it.</p>
              <ul className="flex max-h-56 flex-col gap-0.5 overflow-y-auto" data-declared-paths>
                {declared.map((entry) => (
                  <PathRow
                    key={entry.path}
                    path={entry.path}
                    detail={entry.examples.length > 0 ? `e.g. ${entry.examples.join(" · ")}` : "declared"}
                    faint
                    icon={false}
                    feedback={feedback}
                    onCopy={(path) => void copy(path)}
                  />
                ))}
              </ul>
            </>
          )}

          {data && data.sampled > 0 && (
            <>
              <p className="text-[11px] text-fg-faint">
                From the {data.sampled} most recent — click a path to use it.
              </p>
              <ul className="flex max-h-56 flex-col gap-0.5 overflow-y-auto">
                {data.paths.map((entry) => (
                  // No examples is a REAL finding — the field exists and was null in every sample.
                  <PathRow
                    key={entry.path}
                    path={entry.path}
                    many={entry.repeated}
                    detail={entry.examples.join(" · ") || "empty in every sample"}
                    faint={entry.examples.length === 0}
                    icon
                    feedback={feedback}
                    onCopy={(path) => void copy(path)}
                  />
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
