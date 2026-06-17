import { useEffect, useRef, useState } from "react";

import { ActivityFeed } from "./ActivityFeed";
import { ChatInput } from "./ChatInput";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { activePromptId, promptLandmarks } from "./rail";
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

// The surface is one vertically-scrolling conversation column with an outline rail
// of the user's prompts. The transcript scrolls; the composer is pinned at the
// bottom; the rail jumps to a prompt and tracks the active one as you scroll.
export function Surface({ surface }: { surface: string }) {
  const [{ view, status, title }, sendMessage, stop] = useSurfaceSocket(surface);
  const busy = view.thinking || status === "running";
  const prompts = promptLandmarks(view.activity);

  // Mirror the inferred session title into the browser tab. Falls back to the
  // surface id until a title is inferred, and restores the default on unmount.
  useEffect(() => {
    document.title = title ?? surface;
    return () => {
      document.title = "Claude Visual Interface";
    };
  }, [title, surface]);

  const [railOpen, setRailOpen] = useState(true);
  const [active, setActive] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Stick to the bottom as new content arrives. Pin the scroll container itself —
  // scrollHeight covers the transcript's bottom padding, which scrollIntoView on a
  // zero-height marker would leave below the fold. Re-run when the transcript grows,
  // the last entry streams more text, or the thinking indicator toggles the composer
  // height — each changes content height after the activity count has settled.
  const lastEntryText = view.activity[view.activity.length - 1]?.text ?? "";
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [view.activity.length, lastEntryText, view.thinking]);

  // Scroll-spy: mark the active prompt from the rendered anchors' positions.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const update = () => {
      const top = el.getBoundingClientRect().top;
      const positions = Array.from(el.querySelectorAll<HTMLElement>('[id^="prompt-"]')).map(
        (node) => ({ id: node.id, top: node.getBoundingClientRect().top - top }),
      );
      setActive(activePromptId(positions));
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    return () => el.removeEventListener("scroll", update);
  }, [view.activity.length]);

  function jumpTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2 text-sm">
        <a href="/" className="text-zinc-400 hover:text-zinc-100">
          ← sessions
        </a>
        {prompts.length > 0 ? (
          <button
            type="button"
            onClick={() => setRailOpen((o) => !o)}
            className="text-zinc-400 hover:text-zinc-100"
            aria-label="Toggle outline"
            title="Toggle outline"
          >
            ☰
          </button>
        ) : null}
        <span className="truncate text-zinc-300">{title ?? surface}</span>
        <span className="ml-auto">
          <StatusChip status={status} />
        </span>
      </header>

      <div className="flex min-h-0 flex-1">
        {railOpen && prompts.length > 0 ? (
          <nav className="w-56 shrink-0 space-y-0.5 overflow-auto border-r border-zinc-800 p-2">
            {prompts.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => jumpTo(p.id)}
                title={p.text}
                className={`block w-full truncate rounded px-2 py-1 text-left text-xs ${
                  active === p.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900"
                }`}
              >
                {p.summary ?? p.text}
              </button>
            ))}
          </nav>
        ) : null}

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
          <div className="mx-auto max-w-3xl px-4 py-4">
            <ActivityFeed activity={view.activity} />
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-zinc-800">
        <div className="mx-auto max-w-3xl">
          {busy ? (
            <div className="flex items-center gap-2 px-3 py-1.5 text-xs text-zinc-400">
              <ThinkingIndicator active={view.thinking} />
            </div>
          ) : null}
          <ChatInput onSend={sendMessage} busy={busy} onStop={stop} />
        </div>
      </div>
    </div>
  );
}
