import type { Finding } from "./viewState";

function severityClass(severity: string | null): string {
  switch (severity) {
    case "high":
      return "bg-red-900 text-red-200";
    case "medium":
      return "bg-amber-900 text-amber-200";
    default:
      return "bg-zinc-800 text-zinc-300";
  }
}

function FindingRow({
  finding,
  active,
  onSelect,
}: {
  finding: Finding;
  active: boolean;
  onSelect: (finding: Finding) => void;
}) {
  const lines = finding.anchor ? `:${finding.anchor.range.start}–${finding.anchor.range.end}` : "";
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(finding)}
        className={`block w-full border-b border-zinc-800 p-3 text-left hover:bg-zinc-900 ${
          active ? "bg-zinc-900" : ""
        } ${finding.disposition ? "opacity-50" : ""}`}
      >
        <div className="flex items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-xs ${severityClass(finding.severity)}`}>
            {finding.severity ?? "note"}
          </span>
          <span className="text-sm font-medium">{finding.title}</span>
        </div>
        <div className="mt-1 font-mono text-xs text-zinc-500">
          {finding.file}
          {lines}
        </div>
        {finding.disposition ? (
          <div className="mt-1 text-xs text-zinc-400">→ {finding.disposition}</div>
        ) : null}
      </button>
    </li>
  );
}

export function FindingsPanel({
  findings,
  activeId,
  onSelect,
}: {
  findings: Record<string, Finding>;
  activeId: string | null;
  onSelect: (finding: Finding) => void;
}) {
  const items = Object.values(findings);
  const open = items.filter((f) => !f.disposition).length;
  const hasItems = items.length > 0;

  // Only claim flexible space (and scroll) when there are findings; when empty,
  // sit at content height so the panel doesn't stretch into a big empty box and
  // the transcript above takes the room instead.
  return (
    <div className={`flex min-h-0 flex-col ${hasItems ? "flex-1" : "shrink-0"}`}>
      <div className="border-b border-zinc-800 px-3 py-2 text-sm font-semibold">
        Findings <span className="text-zinc-500">· {items.length} · {open} open</span>
      </div>
      {!hasItems ? (
        <div className="p-3 text-sm text-zinc-500">no findings yet</div>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto">
          {items.map((f) => (
            <FindingRow key={f.id} finding={f} active={f.id === activeId} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </div>
  );
}
