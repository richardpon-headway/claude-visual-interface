import { useCallback, useEffect, useState } from "react";

import type { ImageAttachment, SendMessage, StopAgent } from "./useSurfaceSocket";

// Cap on images per turn. base64 inflates ~33%, so this keeps a realistic batch of
// screenshots inline on the WebSocket frame under the daemon's 16 MB limit; mirrors
// the daemon's own cap.
const MAX_IMAGES = 8;

// The chat box at the bottom of the right pane. Submitting sends a turn to the
// surface's agent; the message echoes back into the transcript as a `user` entry.
// Pasting or dropping image(s) attaches them to the next message (one thumbnail chip
// each, capped at MAX_IMAGES). While a turn is in flight (`busy`), the Send button
// becomes a Stop button in the same slot, and submitting is inert until the turn ends.
export function ChatInput({
  onSend,
  busy = false,
  onStop,
}: {
  onSend: SendMessage;
  busy?: boolean;
  onStop?: StopAgent;
}) {
  const [text, setText] = useState("");
  const [images, setImages] = useState<ImageAttachment[]>([]);
  const [dragging, setDragging] = useState(false);

  // Shared by paste and drop: read an image File and append it as an attachment chip,
  // up to MAX_IMAGES. Existing attachments are kept (accumulate, not replace).
  const attachImageFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result !== "string") return;
      // Strip the `data:<mime>;base64,` prefix — the daemon/SDK want raw base64.
      const comma = result.indexOf(",");
      if (comma < 0) return;
      const att = { media_type: file.type, data: result.slice(comma + 1) };
      setImages((prev) => (prev.length >= MAX_IMAGES ? prev : [...prev, att]));
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
      // Attach every image file in the drop (a single drop can carry several).
      const files = Array.from(e.dataTransfer?.files ?? []).filter((f) =>
        f.type.startsWith("image/"),
      );
      for (const file of files) attachImageFile(file);
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
    // Attach every image in the paste (a folder selection Cmd-C'd carries several).
    const files = Array.from(e.clipboardData.items)
      .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
      .map((it) => it.getAsFile())
      .filter((f): f is File => f !== null);
    if (files.length === 0) return;
    e.preventDefault();
    for (const file of files) attachImageFile(file);
  }

  function send() {
    if (busy) return;
    const trimmed = text.trim();
    if (!trimmed && images.length === 0) return;
    onSend(trimmed, images.length ? images : undefined);
    setText("");
    setImages([]);
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
      {images.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {images.map((img, i) => (
            <div key={i} className="flex items-center gap-1">
              <img
                src={`data:${img.media_type};base64,${img.data}`}
                alt="attachment"
                className="h-10 w-10 rounded border border-zinc-700 object-cover"
              />
              <button
                type="button"
                onClick={() => setImages((prev) => prev.filter((_, j) => j !== i))}
                aria-label="Remove image"
                className="rounded border border-zinc-700 px-1.5 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : null}
      <div className="relative">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={handlePaste}
          onKeyDown={handleKeyDown}
          rows={4}
          placeholder="Ask the agent — paste a screenshot, or “review the diff”… (Shift+Enter for newline)"
          aria-label="Message the agent"
          className="block w-full min-w-0 resize-none rounded border border-zinc-800 bg-zinc-900 px-2 pt-1 pb-11 text-sm"
        />
        {busy ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop the agent"
            className="absolute bottom-2 right-2 rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!text.trim() && images.length === 0}
            className="absolute bottom-2 right-2 rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
          >
            Send
          </button>
        )}
      </div>
    </form>
  );
}
