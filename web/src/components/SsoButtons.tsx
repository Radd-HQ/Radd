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

/**
 * One sign-in button per configured provider (spec 110).
 *
 * The list is its own unauthenticated endpoint rather than a flag on
 * /instance/login-options, because a button needs the provider's id and label —
 * a boolean can only describe the single-provider world spec 40 lived in.
 */
export function SsoButtons() {
  const providers = useQuery({
    queryKey: ["ssoPublicProviders"],
    queryFn: () =>
      api.get<SsoProviderPublic[]>(ApiPath.ssoPublicProviders, { on401: On401.throw }),
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
            href={`${API_BASE}${ssoLoginPath(provider.id)}`}
            className="flex items-center justify-center gap-2.5 rounded-lg border border-strong bg-surface px-4 py-2.5 text-sm font-medium text-fg hover:bg-elevated"
          >
            {provider.kind === SsoKind.google && <GoogleMark />}
            Sign in with {provider.name}
          </a>
        ))}
      </div>
    </div>
  );
}
