import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { API_BASE, ApiPath, On401, ssoLoginPath } from "../lib/constants";
import { SsoKind, type SsoProviderPublic } from "../lib/types";

/** Google's four-colour G. Fixed brand colours — these must NOT theme-invert. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-4 shrink-0" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18C11.25 26.86 11 25.45 11 24s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
}

/** GitHub's mark — monochrome by design, so it follows the button's text colour. */
function GitHubMark() {
  return (
    <svg viewBox="0 0 16 16" className="size-4 shrink-0" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

/**
 * One sign-in button per configured provider (spec 110).
 *
 * The list is its own unauthenticated endpoint rather than a flag on
 * /instance/login-options, because a button needs the provider's id and label —
 * a boolean can only describe the single-provider world spec 40 lived in.
 */
export function SsoButtons({ next = null }: { next?: string | null }) {
  const providers = useQuery({
    queryKey: ["ssoPublicProviders"],
    queryFn: ({ signal }) =>
      api.get<SsoProviderPublic[]>(ApiPath.ssoPublicProviders, { signal, on401: On401.throw }),
    staleTime: Infinity,
    retry: false,
  });

  const rows = providers.data ?? [];
  if (rows.length === 0) return null;

  return (
    <div className="mt-4">
      <div className="mb-3 flex items-center gap-3">
        <span className="h-px flex-1 bg-[var(--color-border-subtle)]" />
        <span className="text-xs text-fg-muted">or</span>
        <span className="h-px flex-1 bg-[var(--color-border-subtle)]" />
      </div>
      <div className="flex flex-col gap-2">
        {rows.map((provider) => (
          <a
            key={provider.id}
            href={`${API_BASE}${ssoLoginPath(provider.id, next ?? undefined)}`}
            className="flex items-center justify-center gap-2.5 rounded-lg border border-strong bg-surface px-4 py-2.5 text-sm font-medium text-fg hover:bg-elevated"
          >
            {provider.kind === SsoKind.google && <GoogleMark />}
            {provider.kind === SsoKind.github && <GitHubMark />}
            Sign in with {provider.name}
          </a>
        ))}
      </div>
    </div>
  );
}
