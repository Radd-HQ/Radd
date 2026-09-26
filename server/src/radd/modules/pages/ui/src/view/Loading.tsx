import { Spinner } from "@radd/plugin-sdk";

/** A page-level pending state: the SDK's spinner, centred in the space the content will take. */
export function Loading({ label }: { label: string }) {
  return (
    <div className="flex justify-center p-10">
      <Spinner label={label} />
    </div>
  );
}
