/** The app's own error and not-found screens (RADD-1528). Before these, a route
 *  that threw or a URL that matched nothing showed the router library's default
 *  output: unstyled, unexplained, and reported to nobody. */

import { useEffect } from "react";
import type { ErrorComponentProps } from "@tanstack/react-router";
import { useRouter } from "@tanstack/react-router";
import { Compass, TriangleAlert } from "lucide-react";
import { Button } from "./Button";
import { RoutePath } from "../lib/constants";
import { ClientErrorSource, reportClientError } from "../lib/report-error";

function Screen({
  icon: Icon,
  title,
  children,
  actions,
}: {
  icon: typeof TriangleAlert;
  title: string;
  children: React.ReactNode;
  actions: React.ReactNode;
}) {
  return (
    <div className="flex min-h-[60vh] w-full items-center justify-center p-6" role="alert">
      <div className="flex max-w-md flex-col items-center gap-3 text-center">
        <Icon size={28} aria-hidden className="text-fg-faint" />
        <h1 className="text-base font-semibold text-heading">{title}</h1>
        <div className="text-row text-fg-secondary">{children}</div>
        <div className="mt-2 flex items-center gap-2">{actions}</div>
      </div>
    </div>
  );
}

/** A route (or anything it rendered) threw. Retry re-runs the route; Reload is for a stale tab. */
export function RouteErrorScreen({ error, reset }: ErrorComponentProps) {
  const router = useRouter();
  useEffect(() => {
    reportClientError(error, ClientErrorSource.route);
  }, [error]);
  const message = error instanceof Error ? error.message : String(error);
  return (
    <Screen
      icon={TriangleAlert}
      title="This page hit an error"
      actions={
        <>
          <Button
            onClick={() => {
              reset();
              void router.invalidate();
            }}
          >
            Try again
          </Button>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </>
      }
    >
      <p>Nothing you saved was lost. The error has been reported.</p>
      {message && <p className="mt-2 break-words font-mono text-meta text-fg-muted">{message}</p>}
    </Screen>
  );
}

export function NotFoundScreen() {
  const router = useRouter();
  return (
    <Screen
      icon={Compass}
      title="There is nothing at this address"
      actions={<Button onClick={() => void router.navigate({ to: RoutePath.home })}>Go to My Work</Button>}
    >
      <p>The link may be old, or the page may have moved or been removed.</p>
    </Screen>
  );
}
