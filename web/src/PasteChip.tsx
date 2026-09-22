import { useState } from "react";

// A collapsed stand-in for one large pasted block, shared by the composer and the
// transcript. Collapsed by default (just a one-line summary); Expand reveals a
// scrollable preview. In the composer it takes an `onRemove` (a ✕ that drops the paste
// before send) and a `capLines` for the truncation tooltip; the transcript renders it
// read-only from a persisted paste (no ✕, never truncated on the way out).
export function PasteChip({
  text,
  dropped = 0,
  capLines,
  onRemove,
}: {
  text: string;
  dropped?: number;
  capLines?: number;
  onRemove?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const lines = text.split("\n").length;
  return (
    <div className="rounded border border-zinc-700 bg-zinc-800/60 text-xs">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span aria-hidden>📄</span>
        <span className="text-zinc-200">Pasted text</span>
        <span className="text-zinc-500">
          · {lines} {lines === 1 ? "line" : "lines"}
        </span>
        <span className="rounded bg-zinc-700 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-300">
          Pasted
        </span>
        {dropped > 0 ? (
          <span
            title={
              capLines != null
                ? `Truncated to the first ${capLines.toLocaleString()} lines`
                : undefined
            }
            className="rounded bg-amber-950 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300"
          >
            ⚠ truncated · {dropped.toLocaleString()} dropped
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse pasted text" : "Expand pasted text"}
          className="ml-auto rounded px-1.5 py-0.5 text-zinc-400 hover:text-zinc-100"
        >
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </button>
        {onRemove ? (
          <button
            type="button"
            onClick={onRemove}
            aria-label="Remove pasted text"
            className="rounded px-1 text-zinc-400 hover:text-zinc-100"
          >
            ×
          </button>
        ) : null}
      </div>
      {expanded ? (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap border-t border-zinc-700 px-2 py-1.5 font-mono text-[11px] text-zinc-300">
          {text}
        </pre>
      ) : null}
    </div>
  );
}
