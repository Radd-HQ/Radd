import { Play } from "lucide-react";

/** Where the script itself lives is the automation node (RADD-1272). This
 * page owns what is instance-wide; the contract is repeated here so an admin
 * reads it where they set the interpreter up. */
export function ContractSection() {
  return (
    <section data-scripts-contract className="flex flex-col gap-2 rounded-[10px] border border-subtle bg-surface p-4">
      <div className="flex items-center gap-2">
        <Play size={15} className="text-accent-text" aria-hidden />
        <h2 className="text-sm font-medium text-heading">Writing a script</h2>
      </div>
      <p className="text-xs text-fg-secondary">
        Drop a <strong className="font-medium text-fg">Run a script</strong> or{" "}
        <strong className="font-medium text-fg">Decide with a script</strong> node on an automation; the
        Python lives on the node, and the automation&rsquo;s versions are its history. A new node arrives
        with this contract filled in:
      </p>
      <pre className="overflow-auto rounded-[8px] border border-subtle bg-base p-3 text-[12px] leading-5 text-fg">{CONTRACT}</pre>
      <p className="text-xs text-fg-secondary">
        A <em>Run a script</em> node publishes the dict <code className="text-fg">main</code> returns: each key
        you declare as an output becomes a <code className="text-fg">{"{{name.key}}"}</code> token downstream.
        A <em>Decide with a script</em> node takes the port <code className="text-fg">main</code> names; a
        failure, a timeout or an unknown name takes <em>unavailable</em>. Scripts run out of process, with a
        short-lived key for the automation&rsquo;s identity: whatever they do through{" "}
        <code className="text-fg">ctx.client</code> is what that identity could do by hand.
      </p>
    </section>
  );
}

const CONTRACT = `def main(ctx):
    ctx.event        # the event that fired (type, actor, payload) — None on a manual/scheduled run
    ctx.items        # the issues this node is acting on, as full read models (list of dicts)
    ctx.item         # the first of them, for the per-item case
    ctx.vars         # values upstream nodes produced: ctx.vars["triage"]["priority"]
    ctx.params       # this node's own params
    ctx.client       # a ready radd_sdk.RaddClient, acting as the automation's identity
    ctx.log("text")  # a line on the run's stderr, shown in the run report
    return {"count": len(ctx.items)}`
