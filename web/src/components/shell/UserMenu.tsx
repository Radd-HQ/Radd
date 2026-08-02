import { useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { CircleUserRound, FlaskConical, LogOut, Moon, Sun } from "lucide-react";
import { Avatar } from "../Avatar";
import { DropdownMenu } from "../DropdownMenu";
import { Theme, getTheme, setTheme } from "../../lib/theme";
import { AuthStatus, logout } from "../../lib/auth";
import { RoutePath } from "../../lib/constants";
import { useAuthState } from "../../lib/hooks";
import { queryKeys } from "../../lib/queries";

export function UserMenu() {
  const authState = useAuthState();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  if (!authState) return null;

  if (authState.status !== AuthStatus.authenticated) {
    return (
      <div
        className="mt-1 flex items-center gap-2 rounded-md bg-elevated/60 px-2 py-1.5 text-[12px] text-amber-400/90"
        title="The auth backend isn't deployed yet; the API is open in dev."
      >
        <FlaskConical size={13} aria-hidden />
        Dev mode — anonymous
      </div>
    );
  }

  const { user } = authState;

  const onLogout = async () => {
    try {
      await logout();
    } finally {
      queryClient.removeQueries({ queryKey: queryKeys.authState });
      void navigate({ to: RoutePath.login });
    }
  };

  const dark = getTheme() === Theme.dark;

  return (
    <DropdownMenu
      label="Account menu"
      side="top"
      widthClass="w-full"
      className="mt-1"
      items={[
        {
          kind: "action",
          label: "Profile",
          icon: CircleUserRound,
          onSelect: () => void navigate({ to: RoutePath.settingsProfile }),
        },
        {
          kind: "action",
          label: dark ? "Light theme" : "Dark theme",
          icon: dark ? Sun : Moon,
          onSelect: () => setTheme(dark ? Theme.light : Theme.dark),
        },
        { kind: "separator" },
        { kind: "action", label: "Log out", icon: LogOut, onSelect: () => void onLogout() },
      ]}
      trigger={({ ref, open, toggle }) => (
        <button
          ref={ref}
          type="button"
          onClick={toggle}
          aria-haspopup="menu"
          aria-expanded={open}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-overlay focus-visible:outline-2 focus-visible:outline-focus cursor-pointer"
        >
          <Avatar user={user} size="sm" />
          <span className="min-w-0">
            <span className="block truncate text-[13px] text-fg">{user.name}</span>
            <span className="block truncate text-[11px] text-fg-muted">{user.email}</span>
          </span>
        </button>
      )}
    />
  );
}
