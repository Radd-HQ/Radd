import { useState } from "react";
import { Smile } from "lucide-react";
import { Popover } from "../Popover";

const SYMBOLS = [
  ["✅", "check done yes"], ["❌", "cross no error"], ["⚠️", "warning attention"],
  ["ℹ️", "information info"], ["❓", "question help"], ["☑️", "checked checkbox"],
  ["⭐", "star favorite"], ["📌", "pin"], ["💡", "idea light bulb"], ["🔔", "bell notification"],
  ["🚀", "rocket launch"], ["🐛", "bug"], ["🔧", "wrench fix"], ["🔒", "lock private"],
  ["📅", "calendar date"], ["⏳", "hourglass waiting"], ["🎯", "target goal"],
  ["👍", "thumbs up approve"], ["👎", "thumbs down"], ["🎉", "celebrate party"],
  ["😊", "smile happy"], ["🙌", "raised hands"], ["❤️", "heart love"],
  ["→", "arrow right"], ["←", "arrow left"], ["↑", "arrow up"], ["↓", "arrow down"],
  ["•", "bullet dot"], ["✓", "tick check"], ["✗", "cross"], ["±", "plus minus"], ["∞", "infinity"],
];

export function SymbolPicker({ onInsert }: { onInsert: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const matches = SYMBOLS.filter(([symbol, name]) => (symbol + name).includes(search.toLowerCase().trim()));
  return <div className="relative">
    <button type="button" title="Emoji and symbols" aria-label="Emoji and symbols" aria-expanded={open}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-fg-secondary hover:bg-elevated"
      onMouseDown={e => e.preventDefault()} onClick={() => { setSearch(""); setOpen(!open); }}><Smile size={16} /></button>
    <Popover open={open} onClose={() => setOpen(false)} label="Emoji and symbols" className="w-64 p-3">
      <input autoFocus aria-label="Search symbols" placeholder="Search symbols…" value={search}
        onChange={e => setSearch(e.target.value)} className="mb-2 w-full rounded border border-subtle bg-base px-2 py-1 text-sm" />
      <div className="grid grid-cols-6 gap-1">
        {matches.map(([symbol, name]) => <button key={symbol} type="button" title={name} aria-label={name}
          className="h-8 rounded text-lg hover:bg-elevated focus-visible:outline-2 focus-visible:outline-focus"
          onMouseDown={e => e.preventDefault()} onClick={() => { onInsert(symbol); setOpen(false); }}>{symbol}</button>)}
      </div>
      {!matches.length && <p className="text-sm text-fg-muted">No matching symbols.</p>}
    </Popover>
  </div>;
}
