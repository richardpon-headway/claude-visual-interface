import type { PendingTurn } from "./viewState";

// The queue of not-yet-running user turns, shown just above the composer so a message
// typed while the agent is busy is visible while it waits its turn. Each row carries a
// bare ✕ to skip (cancel) that turn before it runs — distinct from Stop, which interrupts
// the turn already running. Renders nothing when the queue is empty.
export function PendingQueue({
  queue,
  onSkip,
}: {
  queue: PendingTurn[];
  onSkip: (id: string) => void;
}) {
  if (queue.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1 px-2 py-1.5">
      {queue.map((turn) => (
        <li
          key={turn.id}
          className="flex items-center gap-2 rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1 text-xs text-zinc-400"
        >
          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-500">
            Queued
          </span>
          <span className="min-w-0 flex-1 truncate" title={turn.text}>
            {turn.text}
          </span>
          <button
            type="button"
            onClick={() => onSkip(turn.id)}
            aria-label="Skip queued message"
            title="Skip this queued message"
            className="-mr-0.5 rounded px-1 leading-none text-zinc-500 hover:text-zinc-100"
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  );
}
