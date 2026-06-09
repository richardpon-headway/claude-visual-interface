import { useState } from "react";

import type { SendMessage } from "./useSurfaceSocket";

// The chat box at the bottom of the right pane. Submitting sends a turn to the
// surface's agent; the message echoes back into the transcript as a `user` entry.
export function ChatInput({ onSend }: { onSend: SendMessage }) {
  const [text, setText] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  }

  return (
    <form onSubmit={submit} className="flex gap-2 border-t border-zinc-800 p-2">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Ask the agent — e.g. “review the diff”…"
        aria-label="Message the agent"
        className="min-w-0 flex-1 rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-sm"
      />
      <button
        type="submit"
        disabled={!text.trim()}
        className="rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
      >
        Send
      </button>
    </form>
  );
}
