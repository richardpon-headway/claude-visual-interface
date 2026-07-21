import { useEffect, useRef, useState } from "react";

import { ActivityFeed } from "./ActivityFeed";
import { BackgroundTasks } from "./BackgroundTasks";
import { ChatInput } from "./ChatInput";
import { ErrorBoundary } from "./ErrorBoundary";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { activePromptId, promptLandmarks } from "./rail";
import { useSurfaceSocket } from "./useSurfaceSocket";

// Click-to-edit session title in the header. The committed name is sent to the
// daemon's rename endpoint; the new title flows back over the "title" websocket
// broadcast (which also updates the browser tab), so we don't set it locally.
function EditableTitle({ surface, title }: { surface: string; title: string | null }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  // Escape cancels: it blurs the input, and the resulting blur must skip the commit.
  const cancelRef = useRef(false);

  function begin() {
    setDraft(title ?? "");
    setEditing(true);
  }

  async function commit() {
    setEditing(false);
    if (cancelRef.current) {
      cancelRef.current = false;
      return;
    }
    const next = draft.trim();
    if (!next || next === title) return;
    try {
      await fetch(`/sessions/${encodeURIComponent(surface)}/rename`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: next }),
      });
    } catch {
      // Leave the displayed title untouched; the websocket will reconcile on success.
    }
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            e.currentTarget.blur();
          } else if (e.key === "Escape") {
            cancelRef.current = true;
            e.currentTarget.blur();
          }
        }}
        className="min-w-0 flex-1 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 text-sm text-zinc-100"
      />
    );
  }

  return (
    <button
      type="button"
      onClick={begin}
      title="Rename session"
      className="min-w-0 flex-1 truncate text-left text-zinc-300 hover:text-zinc-100"
    >
      {title ?? surface}
    </button>
  );
}

// The surface is one vertically-scrolling conversation column with an outline rail
// of the user's prompts. The transcript scrolls; the composer is pinned at the
// bottom; the rail jumps to a prompt and tracks the active one as you scroll.
export function Surface({ surface }: { surface: string }) {
  const [
    { view, title, starred },
    sendMessage,
    stop,
    sendAnswer,
    connection,
    setStarred,
    stopTask,
  ] = useSurfaceSocket(surface);
  const busy = view.thinking;
  const prompts = promptLandmarks(view.activity);

  // Toggle the star optimistically, then persist; revert the local flip on failure.
  // No live broadcast in v1 — the home list reconciles on its next load.
  async function toggleStar() {
    const next = !starred;
    setStarred(next);
    try {
      await fetch(`/sessions/${encodeURIComponent(surface)}/${next ? "star" : "unstar"}`, {
        method: "POST",
      });
    } catch {
      setStarred(!next);
    }
  }

  // Mirror the inferred session title into the browser tab. Falls back to the
  // surface id until a title is inferred, and restores the default on unmount.
  useEffect(() => {
    document.title = title ?? surface;
    return () => {
      document.title = "Claude Visual Interface";
    };
  }, [title, surface]);

  // Hidden by default so the conversation gets full width (useful when running
  // several narrow CVI windows side by side). The ☰ button in the header shows it.
  const [railOpen, setRailOpen] = useState(false);
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
        <a href="/sessions" className="text-zinc-400 hover:text-zinc-100">
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
        <EditableTitle surface={surface} title={title} />
        <span className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={toggleStar}
            aria-label={starred ? "Unstar" : "Star"}
            title={starred ? "Unstar" : "Star"}
            className={`text-base leading-none ${starred ? "text-amber-400 hover:text-amber-300" : "text-zinc-600 hover:text-zinc-300"}`}
          >
            {starred ? "★" : "☆"}
          </button>
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
          <div className="px-4 py-4">
            <ErrorBoundary
              fallback={
                <div className="mx-auto w-full max-w-3xl rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3 text-sm text-zinc-400">
                  Something went wrong rendering this conversation. Try reloading; the
                  header and composer above still work.
                </div>
              }
            >
              <ActivityFeed
                activity={view.activity}
                thinking={view.thinking}
                onAnswer={sendAnswer}
              />
            </ErrorBoundary>
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-zinc-800">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center gap-3 px-2 py-1.5 text-xs text-zinc-400">
            {busy ? <ThinkingIndicator active={view.thinking} /> : null}
            <BackgroundTasks tasks={view.background_tasks} onStop={stopTask} />
            {connection !== "open" ? (
              <span className="flex items-center gap-1.5 text-amber-400/90">
                <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                reconnecting…
              </span>
            ) : null}
            <span className="ml-auto text-zinc-500">
              <span className="text-zinc-300">
                {view.session_output_tokens.toLocaleString()} output
              </span>
              {" · "}
              {view.session_input_tokens.toLocaleString()} in
            </span>
          </div>
          <ChatInput onSend={sendMessage} busy={busy} onStop={stop} />
        </div>
      </div>
    </div>
  );
}
