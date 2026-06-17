import { useCallback, useEffect, useState } from "react";

import type { ImageAttachment, SendMessage } from "./useSurfaceSocket";

// The chat box at the bottom of the right pane. Submitting sends a turn to the
// surface's agent; the message echoes back into the transcript as a `user` entry.
// Pasting or dropping an image attaches it to the next message (thumbnail chip).
export function ChatInput({ onSend }: { onSend: SendMessage }) {
  const [text, setText] = useState("");
  const [image, setImage] = useState<ImageAttachment | null>(null);
  const [dragging, setDragging] = useState(false);

  // Shared by paste and drop: read an image File into the attachment chip.
  const attachImageFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") return;
      // Strip the `data:<mime>;base64,` prefix — the daemon/SDK want raw base64.
      const comma = result.indexOf(",");
      if (comma >= 0) setImage({ media_type: file.type, data: result.slice(comma + 1) });
    };
    reader.readAsDataURL(file);
  }, []);

  // Accept image drops anywhere in the window, not just over the composer. The
  // overlay only shows for file drags (not text/link drags), and clears when the
  // cursor leaves the window — element-to-element moves keep relatedTarget set.
  useEffect(() => {
    function isFileDrag(e: DragEvent) {
      return e.dataTransfer?.types.includes("Files") ?? false;
    }
    function onDragOver(e: DragEvent) {
      if (!isFileDrag(e)) return;
      e.preventDefault();
      setDragging(true);
    }
    function onDragLeave(e: DragEvent) {
      // relatedTarget is the node being entered; it's null/absent only when the
      // cursor leaves the window entirely (element-to-element moves keep it set).
      if (!e.relatedTarget) setDragging(false);
    }
    function onDrop(e: DragEvent) {
      e.preventDefault();
      setDragging(false);
      const file = Array.from(e.dataTransfer?.files ?? []).find((f) =>
        f.type.startsWith("image/"),
      );
      if (file) attachImageFile(file);
    }
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [attachImageFile]);

  function handlePaste(e: React.ClipboardEvent) {
    const item = Array.from(e.clipboardData.items).find(
      (it) => it.kind === "file" && it.type.startsWith("image/"),
    );
    const file = item?.getAsFile();
    if (!file) return;
    e.preventDefault();
    attachImageFile(file);
  }

  function send() {
    const trimmed = text.trim();
    if (!trimmed && !image) return;
    onSend(trimmed, image ?? undefined);
    setText("");
    setImage(null);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    send();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Enter sends; Shift+Enter inserts a newline (the textarea's default).
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <form onSubmit={submit} className="flex shrink-0 flex-col gap-2 p-2">
      {dragging ? (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/60 ring-2 ring-inset ring-zinc-400">
          <span className="rounded border border-zinc-600 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200">
            Drop an image to attach
          </span>
        </div>
      ) : null}
      {image ? (
        <div className="flex items-center gap-2">
          <img
            src={`data:${image.media_type};base64,${image.data}`}
            alt="attachment"
            className="h-10 w-10 rounded border border-zinc-700 object-cover"
          />
          <button
            type="button"
            onClick={() => setImage(null)}
            aria-label="Remove image"
            className="rounded border border-zinc-700 px-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
          >
            ×
          </button>
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          rows={4}
          placeholder="Ask the agent — paste a screenshot, or “review the diff”… (Shift+Enter for newline)"
          aria-label="Message the agent"
          className="min-w-0 flex-1 resize-none rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-sm"
        />
        <button
          type="submit"
          disabled={!text.trim() && !image}
          className="rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </form>
  );
}
