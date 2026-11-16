/** Password change and reset (RADD-1529). Before this a local password was set
 *  once, at account creation, and could only be replaced from a shell. */

import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, api } from "../../lib/api";
import { ApiPath, On401, apiUserPasswordPath } from "../../lib/constants";
import { pushToast } from "../../lib/toast";
import type { User } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";
import { TextField } from "../TextField";
import { ErrorText } from "@radd/plugin-sdk";

/** Mirrors the server's `_NewPassword` bound (auth/schemas.py). */
export const PASSWORD_MIN_LENGTH = 8;

interface PasswordChangeResult {
  sessions_ended: number;
}

/** What is wrong with a new password before it is sent, or null. Pure. */
export function newPasswordProblem(password: string, repeat: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) return `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
  if (password !== repeat) return "The two entries do not match.";
  return null;
}

function endedMessage(count: number, whose: string): string {
  if (count === 0) return "";
  return ` ${count} other session${count === 1 ? "" : "s"} of ${whose} signed out.`;
}

/** Profile → Security: the person changes their own, proving the current one. */
export function PasswordPanel() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [touched, setTouched] = useState(false);

  const change = useMutation({
    // A wrong current password is a 401 — say so here, do not bounce to /login.
    mutationFn: () =>
      api.post<PasswordChangeResult>(
        ApiPath.password,
        { current_password: current, new_password: next },
        { on401: On401.throw },
      ),
    onSuccess: (result) => {
      setCurrent("");
      setNext("");
      setRepeat("");
      setTouched(false);
      pushToast(`Password changed.${endedMessage(result.sessions_ended, "yours")}`);
    },
  });

  const problem = newPasswordProblem(next, repeat);
  const wrongCurrent = change.error instanceof ApiError && change.error.status === 401;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem || !current) return;
    change.mutate();
  };

  return (
    <form onSubmit={submit} className="flex max-w-sm flex-col gap-3" data-password-panel>
      <TextField
        label="Current password"
        type="password"
        autoComplete="current-password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        error={wrongCurrent ? "That is not your current password." : undefined}
      />
      <TextField
        label="New password"
        type="password"
        autoComplete="new-password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
      />
      <TextField
        label="New password, again"
        type="password"
        autoComplete="new-password"
        value={repeat}
        onChange={(event) => setRepeat(event.target.value)}
        error={touched && problem ? problem : undefined}
      />
      {change.isError && !wrongCurrent && <ErrorText error={change.error} />}
      <div>
        <Button type="submit" disabled={change.isPending || !current || !next}>
          {change.isPending ? "Changing…" : "Change password"}
        </Button>
      </div>
      <p className="text-xs text-fg-muted">
        Your other signed-in browsers are signed out. This one stays.
      </p>
    </form>
  );
}

/** Settings → Users: an administrator sets a new password for a local account. */
export function ResetPasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [touched, setTouched] = useState(false);

  const reset = useMutation({
    mutationFn: () =>
      api.put<PasswordChangeResult>(apiUserPasswordPath(user.id), { new_password: next }),
    onSuccess: (result) => {
      pushToast(`Password set for ${user.name}.${endedMessage(result.sessions_ended, "theirs")}`);
      onClose();
    },
  });

  const problem = newPasswordProblem(next, repeat);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (problem) return;
    reset.mutate();
  };

  return (
    <Modal title={`Set a new password for ${user.name}`} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3" data-reset-password>
        <p className="text-row text-fg-secondary">
          {user.email} is signed out everywhere and must use the new password. Radd does not send
          it: give it to them yourself, and ask them to change it in Profile.
        </p>
        <TextField
          label="New password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
          hint={`At least ${PASSWORD_MIN_LENGTH} characters.`}
        />
        <TextField
          label="New password, again"
          type="password"
          autoComplete="new-password"
          value={repeat}
          onChange={(event) => setRepeat(event.target.value)}
          error={touched && problem ? problem : undefined}
        />
        {reset.isError && <ErrorText error={reset.error} />}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" disabled={reset.isPending || !next}>
            {reset.isPending ? "Setting…" : "Set password and sign them out"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
