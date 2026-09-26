import { useCapabilities } from "@radd/plugin-sdk";
import { useLayoutEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";

/** Abort transport and suppress continuations when a surface leaves or its input
 * revision changes. Cancellation cannot undo a write already accepted by the server. */
export function useAutomationMutation<T, V = void>(options: {
  mutationFn: (variables: V, signal: AbortSignal) => Promise<T>;
  onSuccess?: (data: T, variables: V) => unknown;
}, revision = "") {
  const caps = useCapabilities();
  const identity = JSON.stringify([revision, caps?.plugins, caps?.remotes]);
  const lifetime = useRef({active: true, revision, epoch: 0, pending: new Set<AbortController>()});
  useLayoutEffect(() => {
    const owner = lifetime.current;
    owner.revision = revision;
    owner.epoch++;
    for (const controller of owner.pending) controller.abort();
    owner.pending.clear();
  }, [identity]);
  useLayoutEffect(() => {
    lifetime.current.active = true;
    return () => {
      lifetime.current.active = false;
      lifetime.current.epoch++;
      for (const controller of lifetime.current.pending) controller.abort();
      lifetime.current.pending.clear();
    };
  }, []);
  const mutation = useMutation({
    mutationFn: async (variables: V) => {
      const owner = lifetime.current;
      if (!owner.active) throw new DOMException("This editor has closed", "AbortError");
      const epoch = owner.epoch;
      const controller = new AbortController();
      owner.pending.add(controller);
      try {
        const data = await options.mutationFn(variables, controller.signal);
        if (!owner.active || owner.epoch !== epoch || controller.signal.aborted) throw new DOMException("This request is no longer current", "AbortError");
        // Invoke before handing results back to TanStack, so stale requests never run callbacks.
        await options.onSuccess?.(data, variables);
        return data;
      } finally { owner.pending.delete(controller); }
    },
    gcTime: 0,
  });
  return mutation;
}
