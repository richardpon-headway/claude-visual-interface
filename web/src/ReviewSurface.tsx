import { useEffect, useRef } from "react";

import { ActivityFeed } from "./ActivityFeed";
import { ChatInput } from "./ChatInput";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { useSurfaceSocket } from "./useSurfaceSocket";

function StatusChip({ status }: { status: string | null }) {
  const cls =
    status === "ready"
      ? "bg-emerald-900 text-emerald-200"
      : status === "error"
        ? "bg-red-900 text-red-200"
        : status === "running"
          ? "bg-sky-900 text-sky-200"
          : status === "stopped"
            ? "bg-amber-900 text-amber-200"
            : "bg-zinc-800 text-zinc-400";
  return (
    <span className={`flex items-center gap-1.5 rounded px-2 py-0.5 text-xs ${cls}`}>
      {status === "running" ? (
        <span className="inline-block h-2 w-2 animate-spin rounded-full border border-current border-t-transparent" />
      ) : null}
      {status ?? "unknown"}
    </span>
  );
}

// The surface is one vertically-scrolling conversation column: the transcript
// scrolls; the composer (thinking/Stop + input) is pinned at the bottom. Both are
// centered to the same readable max-width.
export function ReviewSurface({ surface }: { surface: string }) {
  const [{ view, status, title }, sendMessage, stop] = useSurfaceSocket(surface);
  const busy = view.thinking || status === "running";

  // Stick to the bottom as new content arrives.
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [view.activity.length, view.thinking]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2 text-sm">
        <a href="/" className="text-zinc-400 hover:text-zinc-100">
          ← sessions
        </a>
        <span className="truncate text-zinc-300">{title ?? surface}</span>
        <span className="ml-auto">
          <StatusChip status={status} />
        </span>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-3xl px-4 py-4">
          <ActivityFeed activity={view.activity} />
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="shrink-0 border-t border-zinc-800">
        <div className="mx-auto max-w-3xl">
          {busy ? (
            <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-zinc-400">
              <ThinkingIndicator active={view.thinking} />
              <button
                type="button"
                onClick={stop}
                className="ml-auto rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                Stop
              </button>
            </div>
          ) : null}
          <ChatInput onSend={sendMessage} />
        </div>
      </div>
    </div>
  );
}
