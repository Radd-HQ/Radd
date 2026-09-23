import { useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ImageUp, Trash2 } from "lucide-react";
import { ApiError, api } from "../../lib/api";
import { API_BASE, ApiPath } from "../../lib/constants";
import { queryKeys } from "../../lib/queries";
import type { Me } from "../../lib/types";
import { Button } from "../Button";
import { ErrorText } from "../ErrorText";

type AvatarRead = { avatar_url: string | null };

/** An uploaded picture is served by Radd; anything else came from the IdP. */
function isUploaded(url: string | null | undefined): boolean {
  return !!url && url.startsWith(`${API_BASE}${ApiPath.users}/`);
}

async function uploadPicture(file: File): Promise<AvatarRead> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}${ApiPath.myAvatar}`, {
    method: "PUT",
    credentials: "include",
    body: form,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as AvatarRead;
}

/**
 * RADD-1295: upload, replace or remove your picture. It shows instead of the
 * colour/emoji wherever you appear; removing an upload falls back to your
 * sign-in provider's picture if it sent one, then to the colour/emoji.
 */
export function ProfilePicture({ user }: { user: Me }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.authState });
    // Pictures ride on item/comment/people reads too — refresh the world lazily.
    void queryClient.invalidateQueries();
  };
  const upload = useMutation({ mutationFn: uploadPicture, onSuccess: refresh });
  const remove = useMutation({
    mutationFn: () => api.delete<AvatarRead>(ApiPath.myAvatar),
    onSuccess: refresh,
  });
  const uploaded = isUploaded(user.avatar_url);
  const busy = upload.isPending || remove.isPending;

  return (
    <div className="flex flex-col gap-1.5" data-profile-picture>
      <div className="flex items-center gap-2">
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          className="hidden"
          aria-label="Choose a picture"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) upload.mutate(file);
          }}
        />
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => input.current?.click()}>
          <ImageUp size={13} aria-hidden />
          {upload.isPending ? "Uploading…" : uploaded ? "Replace picture" : "Upload picture"}
        </Button>
        {uploaded && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove.mutate()}>
            <Trash2 size={13} aria-hidden />
            Remove picture
          </Button>
        )}
      </div>
      {!uploaded && user.avatar_url && (
        <p className="text-xs text-fg-muted">Showing the picture from your sign-in provider.</p>
      )}
      {upload.isError && <ErrorText error={upload.error} />}
      {remove.isError && <ErrorText error={remove.error} />}
    </div>
  );
}
