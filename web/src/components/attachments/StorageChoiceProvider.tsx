import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { HardDrive } from "lucide-react";
import type { UploadOption } from "../../lib/types";
import { Button } from "../Button";
import { Modal } from "../Modal";

interface StorageChoiceContextValue {
  /** Pop the storage prompt; resolves the picked host id, or null on dismiss. */
  choose: (options: UploadOption[]) => Promise<string | null>;
}

const StorageChoiceContext = createContext<StorageChoiceContextValue | null>(null);

/**
 * The "where should this file be stored?" prompt (spec 102) — the useConfirm
 * promise pattern lifted to app scope: every upload seam awaits
 * `useStorageChoice().choose(options)` and the ONE modal mounted here
 * (app-layout) answers it. Dismiss resolves null — the caller cancels the
 * whole upload gesture.
 */
export function StorageChoiceProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<UploadOption[] | null>(null);
  const resolverRef = useRef<((hostId: string | null) => void) | null>(null);

  const choose = useCallback((next: UploadOption[]) => {
    // A second prompt before the first settles would orphan the first promise —
    // its awaiter would hang forever. Resolve it null (cancel, the safe answer)
    // before taking over the modal.
    resolverRef.current?.(null);
    setOptions(next);
    return new Promise<string | null>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  const settle = (hostId: string | null) => {
    resolverRef.current?.(hostId);
    resolverRef.current = null;
    setOptions(null);
  };

  const value = useMemo(() => ({ choose }), [choose]);

  return (
    <StorageChoiceContext.Provider value={value}>
      {children}
      {options && (
        <Modal title="Where should this file be stored?" onClose={() => settle(null)}>
          <p className="mb-3 text-[13px] text-fg-secondary">
            A storage rule asks uploaders to pick. Closing this cancels the upload.
          </p>
          <div className="flex flex-col gap-2">
            {options.map((option) => (
              <Button
                key={option.id}
                variant="secondary"
                onClick={() => settle(option.id)}
                className="justify-start"
              >
                <HardDrive size={14} className="text-fg-muted" aria-hidden />
                {option.name}
              </Button>
            ))}
          </div>
        </Modal>
      )}
    </StorageChoiceContext.Provider>
  );
}

/** The prompt handle; throws when the provider isn't mounted (app-layout). */
export function useStorageChoice(): StorageChoiceContextValue {
  const context = useContext(StorageChoiceContext);
  if (!context) {
    throw new Error("useStorageChoice must be used inside <StorageChoiceProvider>");
  }
  return context;
}
