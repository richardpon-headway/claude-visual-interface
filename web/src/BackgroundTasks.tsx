import { useEffect, useRef, useState } from "react";

import type { StopTask } from "./useSurfaceSocket";
import type { BackgroundTask } from "./viewState";

// A dedicated, non-blocking indicator for background tasks (a launched
// run_in_background shell). It's deliberately separate from the "thinking" spinner:
// thinking means a turn is actively streaming (and gates the composer), whereas this
// just reports work chugging along in the background — the composer stays usable so a
// prompt can be sent while a task runs. Echoes the Claude CLI's background-shell feel:
// a spinner, the task label, elapsed time, and a stop control.
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const TICK_MS = 120;

function elapsedLabel(startMs: number, nowMs: number): string {
  const s = Math.max(0, Math.floor((nowMs - startMs) / 1000));
  return s >= 60 ? `${Math.floor(s / 60)}m${s % 60}s` : `${s}s`;
}

export function BackgroundTasks({
  tasks,
  onStop,
}: {
  tasks: BackgroundTask[];
  onStop: StopTask;
}) {
  // When each task id was first seen, so elapsed is measured from when it appeared
  // (the daemon doesn't ship a start timestamp). Survives re-renders; pruned as tasks
  // finish so a recycled id restarts its clock.
  const firstSeen = useRef<Map<string, number>>(new Map());
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const seen = firstSeen.current;
    const now = Date.now();
    const live = new Set(tasks.map((t) => t.task_id));
    for (const t of tasks) if (!seen.has(t.task_id)) seen.set(t.task_id, now);
    for (const id of [...seen.keys()]) if (!live.has(id)) seen.delete(id);
  }, [tasks]);

  // One timer drives both the spinner frame and the elapsed counters; only runs while
  // something is in flight.
  useEffect(() => {
    if (tasks.length === 0) return;
    const id = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(id);
  }, [tasks.length]);

  if (tasks.length === 0) return null;

  const now = Date.now();
  const frame = FRAMES[tick % FRAMES.length];
  const stopBtn =
    "rounded border border-violet-500/40 px-1.5 text-[11px] text-violet-300/90 hover:bg-violet-500/10";

  // A single task reads inline; several collapse to a count with a stop-all, then a row
  // per task so each is individually cancelable.
  if (tasks.length === 1) {
    const task = tasks[0];
    const start = firstSeen.current.get(task.task_id) ?? now;
    return (
      <span className="flex items-center gap-2 text-violet-300">
        <span className="font-mono">{frame}</span>
        <span className="truncate" title={task.description}>
          {task.description}
        </span>
        <span className="text-zinc-500">({elapsedLabel(start, now)})</span>
        <button type="button" onClick={() => onStop(task.task_id)} className={stopBtn}>
          ✕ stop
        </button>
      </span>
    );
  }

  return (
    <span className="flex flex-col gap-1">
      <span className="flex items-center gap-2 text-violet-300">
        <span className="font-mono">{frame}</span>
        <span>{tasks.length} background tasks</span>
        <button
          type="button"
          onClick={() => tasks.forEach((t) => onStop(t.task_id))}
          className={stopBtn}
        >
          stop all
        </button>
      </span>
      {tasks.map((task) => {
        const start = firstSeen.current.get(task.task_id) ?? now;
        return (
          <span key={task.task_id} className="flex items-center gap-2 pl-5 text-zinc-400">
            <span className="truncate" title={task.description}>
              {task.description}
            </span>
            <span className="text-zinc-600">({elapsedLabel(start, now)})</span>
            <button type="button" onClick={() => onStop(task.task_id)} className={stopBtn}>
              ✕
            </button>
          </span>
        );
      })}
    </span>
  );
}
