import { AlertTriangle, ArrowRight, UserPlus } from "lucide-react";
import {
  ImportMatchKind,
  ImportResolution,
  ImportStatus,
  type ImportCandidate,
  type ImportResolutionEntry,
  type ImportResolutionValue,
} from "../../lib/types";

const MATCH_REASON: Record<string, string> = {
  [ImportMatchKind.email]: "same email",
  [ImportMatchKind.username]: "AD username matches this address",
  [ImportMatchKind.name]: "same display name",
};

/**
 * Step 2 of importing users from AD (spec 88): what each selected person would
 * do to the accounts already here, and the admin's decision per row.
 *
 * Only conflicts need a decision. `new` and `linked` rows are shown as a plain
 * summary so the count adds up, but they carry no choice — there is nothing
 * ambiguous about them.
 */
export function DirectoryImportReview({
  candidates,
  choices,
  onChoose,
}: {
  candidates: ImportCandidate[];
  choices: Record<string, ImportResolutionEntry>;
  onChoose: (email: string, entry: ImportResolutionEntry) => void;
}) {
  const conflicts = candidates.filter((c) => c.status === ImportStatus.conflict);
  const plain = candidates.filter((c) => c.status !== ImportStatus.conflict);

  return (
    <div className="flex flex-col gap-3">
      {plain.length > 0 && (
        <p className="text-xs text-fg-muted">
          {plain.filter((c) => c.status === ImportStatus.new).length} new account(s),{" "}
          {plain.filter((c) => c.status === ImportStatus.linked).length} already here (their
          name will be refreshed from AD).
        </p>
      )}

      {conflicts.length === 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-emerald-400">
          <UserPlus size={13} aria-hidden />
          No duplicates — nothing to decide.
        </p>
      ) : (
        <>
          <p className="flex items-start gap-1.5 text-xs text-amber-200">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" aria-hidden />
            <span>
              {conflicts.length} of these look like people already in Radd under a different
              email. Choose what happens to each — <strong>Overwrite</strong> keeps their
              existing account and history, just re-addressed to AD.
            </span>
          </p>
          <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
            {conflicts.map((candidate) => {
              const choice = choices[candidate.email];
              const resolution = choice?.resolution ?? candidate.suggested;
              const targetId = choice?.target_user_id ?? candidate.matches[0]?.user_id ?? null;
              const pick = (next: ImportResolutionValue, target: string | null) =>
                onChoose(candidate.email, {
                  email: candidate.email,
                  resolution: next,
                  target_user_id: target,
                });
              // Merge only means something when the AD address is ALREADY here —
              // otherwise there is one account and overwriting it is the move.
              const exact = candidate.matches.find((m) => m.kind === ImportMatchKind.email);
              const lookAlikes = candidate.matches.filter(
                (m) => m.kind !== ImportMatchKind.email,
              );

              return (
                <li
                  key={candidate.email}
                  className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2.5"
                >
                  <p className="text-[13px] text-heading">
                    {candidate.name}{" "}
                    <span className="text-xs text-fg-muted">
                      {candidate.email} · {candidate.username}
                    </span>
                  </p>

                  <ul className="mt-1.5 flex flex-col gap-1">
                    {candidate.matches.map((match) => (
                      <li key={match.user_id} className="flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="text-fg-secondary">{match.name}</span>
                        <span className="text-fg-muted">{match.email}</span>
                        <span className="rounded border border-strong px-1 py-px text-[10px] text-fg-muted">
                          {MATCH_REASON[match.kind]}
                        </span>
                        {!match.active && (
                          <span className="rounded border border-strong px-1 py-px text-[10px] text-fg-muted">
                            deactivated
                          </span>
                        )}
                        {lookAlikes.length > 1 && match.kind !== ImportMatchKind.email && (
                          <label className="flex items-center gap-1 text-[11px] text-fg-muted">
                            <input
                              type="radio"
                              name={`target-${candidate.email}`}
                              checked={targetId === match.user_id}
                              onChange={() => pick(resolution, match.user_id)}
                              className="accent-accent"
                            />
                            this one
                          </label>
                        )}
                      </li>
                    ))}
                  </ul>

                  <div className="mt-2 flex flex-wrap gap-3">
                    {(exact
                      ? [ImportResolution.merge, ImportResolution.create, ImportResolution.skip]
                      : [
                          ImportResolution.overwrite,
                          ImportResolution.create,
                          ImportResolution.skip,
                        ]
                    ).map((option) => (
                      <label
                        key={option}
                        className="flex items-center gap-1.5 text-xs text-fg cursor-pointer"
                      >
                        <input
                          type="radio"
                          name={`resolution-${candidate.email}`}
                          checked={resolution === option}
                          onChange={() => pick(option, targetId)}
                          className="accent-accent"
                        />
                        {LABELS[option]}
                      </label>
                    ))}
                  </div>

                  <p className="mt-1.5 flex items-center gap-1 text-[11px] text-fg-muted">
                    <ArrowRight size={11} aria-hidden />
                    {describe(resolution, candidate, targetId)}
                  </p>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

const LABELS: Record<string, string> = {
  [ImportResolution.overwrite]: "Overwrite existing",
  [ImportResolution.merge]: "Merge into AD account",
  [ImportResolution.create]: "Keep both",
  [ImportResolution.skip]: "Skip",
};

/** Spell out the consequence — these are irreversible and easy to misread. */
function describe(
  resolution: ImportResolutionValue,
  candidate: ImportCandidate,
  targetId: string | null,
): string {
  const target = candidate.matches.find((m) => m.user_id === targetId) ?? candidate.matches[0];
  switch (resolution) {
    case ImportResolution.overwrite:
      return `${target?.email} becomes ${candidate.email} — same account, so all their issues, comments and worklogs follow.`;
    case ImportResolution.merge:
      return `${target?.email} is folded into ${candidate.email} and deactivated; everything it owns moves across.`;
    case ImportResolution.create:
      return `A separate account for ${candidate.email}; the existing one is left as it is.`;
    default:
      return "Nothing is imported for this person.";
  }
}
