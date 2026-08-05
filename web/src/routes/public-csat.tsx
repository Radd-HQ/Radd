import { useState, type FormEvent } from "react";
import { useParams, useSearch } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Star } from "lucide-react";
import { api, errorMessage } from "../lib/api";
import { apiPublicCsatPath } from "../lib/constants";
import { publicCsatQuery, queryKeys } from "../lib/queries";
import type { PublicCsat, PublicCsatSubmit } from "../lib/types";
import { Button } from "../components/Button";
import { RaddTile } from "../components/RaddMark";
import { Spinner } from "../components/Spinner";
import { ErrorText } from "../components/ErrorText";

const RATING_LABELS: Record<number, string> = {
  1: "Very dissatisfied",
  2: "Dissatisfied",
  3: "Neutral",
  4: "Satisfied",
  5: "Very satisfied",
};

/**
 * PUBLIC tokened CSAT rating page (spec 65) — route `/public/csat/$token`,
 * root-level and OUTSIDE the auth gate (the spec-62 public-form idiom). The
 * survey email's five links land here with `?rating=N` preselecting a star;
 * the page POSTs, so a mail scanner prefetching a link never records anything.
 * Re-submits are allowed (latest wins) — an already-answered survey renders
 * with the current rating selected.
 */
export function PublicCsatPage() {
  const { token = "" } = useParams({ strict: false });
  const search = useSearch({ strict: false }) as { rating?: number };
  const survey = useQuery(publicCsatQuery(token));

  return (
    <main className="flex min-h-screen justify-center bg-base px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5">
          <RaddTile className="size-8 rounded-lg" />
          <div>
            <h1 className="text-base font-semibold text-heading">Radd</h1>
            <p className="text-xs text-fg-muted">How did we do?</p>
          </div>
        </div>
        {survey.isPending ? (
          <Spinner label="Loading survey…" />
        ) : survey.isError ? (
          <p className="text-sm text-fg-secondary">
            This survey link isn't available: {errorMessage(survey.error)}
          </p>
        ) : (
          <RatingForm token={token} survey={survey.data} preselected={search.rating} />
        )}
      </div>
    </main>
  );
}

function RatingForm({
  token,
  survey,
  preselected,
}: {
  token: string;
  survey: PublicCsat;
  preselected?: number;
}) {
  const queryClient = useQueryClient();
  // Priority: the emailed link's ?rating, else a previously recorded answer.
  const initial = preselected && preselected >= 1 && preselected <= 5 ? preselected : survey.rating;
  const [rating, setRating] = useState<number | null>(initial ?? null);
  const [hovered, setHovered] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const submit = useMutation({
    mutationFn: () => {
      const body: PublicCsatSubmit = { rating: rating ?? 0, comment: comment.trim() };
      return api.post<PublicCsat>(apiPublicCsatPath(token), body);
    },
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.publicCsat(token), result);
      setSubmitted(true);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (rating !== null) submit.mutate();
  };

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-subtle bg-surface/40 p-6">
      <header className="flex flex-col gap-1 border-b border-subtle pb-4">
        <p className="text-[11px] font-medium uppercase tracking-wide text-accent-text">
          Satisfaction survey
        </p>
        <h2 className="text-lg font-semibold text-heading">
          <span className="font-mono text-accent-text">{survey.item_key}</span> {survey.item_title}
        </h2>
      </header>

      {submitted ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-5">
          <p className="flex items-center gap-2 text-sm text-emerald-300">
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
                      className={active ? "fill-amber-400 text-amber-400" : "text-fg-faint"}
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

          {submit.isError && (
            <ErrorText size="sm" error={submit.error} />
          )}

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
          className={(value ?? 0) >= star ? "fill-amber-400 text-amber-400" : "text-fg-faint"}
        />
      ))}
    </span>
  );
}
