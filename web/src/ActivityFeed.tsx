import type { ActivityEntry } from "./viewState";

function kindLabel(kind: string): string {
  switch (kind) {
    case "tool":
      return "tool";
    case "result":
      return "result";
    case "user":
      return "you";
    default:
      return "";
  }
}

function ActivityRow({ entry }: { entry: ActivityEntry }) {
  const label = kindLabel(entry.kind);
  const isTool = entry.kind === "tool";
  const isUser = entry.kind === "user";
  // The user's own turns read as a distinct, accented bubble in the transcript.
  if (isUser) {
    return (
      <li className="border-b border-zinc-900 px-3 py-1.5 text-xs">
        <span className="mr-2 rounded bg-indigo-900 px-1.5 py-0.5 font-mono text-[10px] uppercase text-indigo-200">
          you
        </span>
        <span className="text-zinc-100">{entry.text}</span>
      </li>
    );
  }
  return (
    <li className="border-b border-zinc-900 px-3 py-1.5 text-xs">
      {label ? (
        <span className="mr-2 rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-400">
          {label}
        </span>
      ) : null}
      <span className={isTool ? "font-mono text-sky-300" : "text-zinc-300"}>{entry.text}</span>
    </li>
  );
}

// A read-only, scrolling feed of the review session's narration: Claude's text,
// tool calls, and run results, in arrival order. Presentational over the buffered
// activity list (live updates and the connect snapshot both flow through it).
export function ActivityFeed({ activity }: { activity: ActivityEntry[] }) {
  return (
    <div className="flex min-h-0 flex-col border-b border-zinc-800">
      <div className="border-b border-zinc-800 px-3 py-2 text-sm font-semibold">
        Activity <span className="text-zinc-500">· {activity.length}</span>
      </div>
      {activity.length === 0 ? (
        <div className="p-3 text-sm text-zinc-500">no activity yet</div>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto">
          {activity.map((entry, i) => (
            <ActivityRow key={i} entry={entry} />
          ))}
        </ul>
      )}
    </div>
  );
}
