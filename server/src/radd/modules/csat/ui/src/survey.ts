import { queryOptions } from "@tanstack/react-query";
import { api } from "@radd/plugin-sdk";

/**
 * The public survey's wire (spec 65), owned by the plugin since RADD-1401. `/public/csat/{token}`
 * is csat's own unauthenticated router: the token IS the credential (404 when unknown), GET renders
 * and POST rates — the emailed links only PRESELECT a star, so a mail scanner prefetching one can
 * never record a rating.
 */

/** Where the survey email's links land; `$token` is captured and handed to the page. */
export const SURVEY_PAGE = "/public/csat/$token";

/** GET/POST /public/csat/{token} — the rating page's payload. */
export interface PublicSurvey {
  item_key: string;
  item_title: string;
  rating: number | null;
  responded_at: string | null;
}

export interface SurveyAnswer {
  rating: number;
  comment: string;
}

const surveyPath = (token: string) => `/public/csat/${encodeURIComponent(token)}`;

/** Keyed under the plugin's name, so withdrawing csat drops it (plugin-loader `withdraw`). */
export const surveyKey = (token: string) => ["csat", "survey", token] as const;

export const surveyQuery = (token: string) =>
  queryOptions({
    queryKey: surveyKey(token),
    queryFn: ({ signal }) => api.get<PublicSurvey>(surveyPath(token), { signal }),
    retry: false,
  });

export const submitSurvey = (token: string, answer: SurveyAnswer) =>
  api.post<PublicSurvey>(surveyPath(token), answer);
