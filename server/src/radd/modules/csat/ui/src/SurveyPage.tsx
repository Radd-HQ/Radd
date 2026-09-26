import { useState, type FormEvent } from "react";
import { useSearch } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Star } from "lucide-react";
import { Button, ErrorText, Spinner, errorMessage } from "@radd/plugin-sdk";
import { submitSurvey, surveyKey, surveyQuery, type PublicSurvey } from "./survey";

const RATING_LABELS: Record<number, string> = {
  1: "Very dissatisfied",
  2: "Dissatisfied",
  3: "Neutral",
  4: "Satisfied",
  5: "Very satisfied",
};

/** A star `?rating=` preselects: the survey email's five links carry one each. */
function preselectedRating(search: Record<string, unknown>): number | undefined {
  const rating = Number(search.rating);
  return Number.isInteger(rating) && rating >= 1 && rating <= 5 ? rating : undefined;
}

/**
 * The PUBLIC tokened rating page (spec 65) — csat's `public.page` contribution at
 * `/public/csat/$token` since RADD-1401, drawn inside the host's public frame (no shell, no sign-in
 * gate). The survey email's five links land here with `?rating=N` preselecting a star; the page
 * POSTs, so a mail scanner prefetching a link never records anything. Re-submits are allowed
 * (latest wins) — an already-answered survey renders with the current rating selected.
 */
export function SurveyPage({ token }: { token: string }) {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  const survey = useQuery(surveyQuery(token));

  if (survey.isPending) return <Spinner label="Loading survey…" />;
  if (survey.isError) {
    return (
      <p className="text-sm text-fg-secondary" data-csat-survey="unavailable">
        This survey link isn't available: {errorMessage(survey.error)}
      </p>
    );
  }
  return <RatingForm token={token} survey={survey.data} preselected={preselectedRating(search)} />;
}

function RatingForm({
  token,
  survey,
  preselected,
}: {
  token: string;
  survey: PublicSurvey;
  preselected?: number;
}) {
  const queryClient = useQueryClient();
  // Priority: the emailed link's ?rating, else a previously recorded answer.
  const [rating, setRating] = useState<number | null>(preselected ?? survey.rating ?? null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const submit = useMutation({
    mutationFn: () => submitSurvey(token, { rating: rating ?? 0, comment: comment.trim() }),
    onSuccess: (result) => {
      queryClient.setQueryData(surveyKey(token), result);
      setSubmitted(true);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (rating !== null) submit.mutate();
  };

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-subtle bg-surface/40 p-6" data-csat-survey={token}>
      <header className="flex flex-col gap-1 border-b border-subtle pb-4">
        <p className="text-[11px] font-medium uppercase tracking-wide text-accent-text">
          Satisfaction survey · How did we do?
        </p>
        <h2 className="text-lg font-semibold text-heading">
          <span className="font-mono text-accent-text">{survey.item_key}</span> {survey.item_title}
        </h2>
      </header>

      {submitted ? (
        <div
          className="flex flex-col items-start gap-3 rounded-lg border border-status-success/30 bg-status-success/5 p-5"
          data-csat-recorded
        >
          <p className="flex items-center gap-2 text-sm text-status-success-ink">
            <CheckCircle2 size={16} aria-hidden />
            Thanks — your rating has been recorded.
          </p>
          <StarRow value={rating} />
          <Button variant="ghost" onClick={() => setSubmitted(false)}>
            Change my rating
          </Button>
        </div>
      ) : (
        <form onSubmit={onSubmit} className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <p className="text-sm text-fg">
              How satisfied are you with the way your request was handled?
            </p>
            {survey.responded_at && (
              <p className="text-xs text-fg-muted">
                You already answered — submitting again replaces your previous rating.
              </p>
            )}
            <div
              className="flex items-center gap-1"
              role="radiogroup"
              aria-label="Rating from 1 to 5 stars"
              onMouseLeave={() => setHovered(null)}
            >
              {[1, 2, 3, 4, 5].map((value) => {
                const active = (hovered ?? rating ?? 0) >= value;
                return (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={rating === value}
                    aria-label={`${value} — ${RATING_LABELS[value]}`}
                    title={RATING_LABELS[value]}
                    onClick={() => setRating(value)}
                    onMouseEnter={() => setHovered(value)}
                    className="cursor-pointer rounded p-1 focus-visible:outline-2 focus-visible:outline-focus"
                  >
                    <Star
                      size={28}
                      aria-hidden
                      className={active ? "fill-status-warning text-status-warning" : "text-fg-faint"}
                    />
                  </button>
                );
              })}
              <span className="ml-2 text-sm text-fg-secondary">
                {rating ? RATING_LABELS[rating] : "Pick a rating"}
              </span>
            </div>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-fg-secondary">Anything to add? (optional)</span>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="What went well, what could be better…"
              className="rounded-md border border-subtle bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-faint focus:outline-2 focus:outline-offset-1 focus:outline-focus"
            />
          </label>

          {submit.isError && <ErrorText size="sm" error={submit.error} />}

          <div className="flex justify-end">
            <Button type="submit" disabled={rating === null || submit.isPending}>
              {submit.isPending ? "Sending…" : "Send rating"}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/** A read-only star strip (the thanks state). */
function StarRow({ value }: { value: number | null }) {
  return (
    <span className="flex items-center gap-0.5" aria-label={`${value ?? 0} of 5 stars`}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Star
          key={star}
          size={18}
          aria-hidden
          className={(value ?? 0) >= star ? "fill-status-warning text-status-warning" : "text-fg-faint"}
        />
      ))}
    </span>
  );
}
