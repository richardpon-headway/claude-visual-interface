import { useCallback, useEffect, useRef, useState } from "react";

import type { ImageAttachment, SendMessage, StopAgent } from "./useSurfaceSocket";

// Cap on images per turn. Images ride inline as base64 (+~33%) on the WebSocket frame;
// the daemon raises its frame limit to 64 MB to fit this batch. Mirrors the daemon's
// own cap (_MAX_IMAGES_PER_TURN in daemon/main.py).
const MAX_IMAGES = 32;

// A plain-text paste past either bound gets lifted out of the textarea into a collapsed
// chip instead of flooding the composer (mirrors how editors like Eddy handle a big
// paste). The chip's content is stitched back into the message at send time, so the
// agent still receives the full text — this is purely a composer-space affordance.
const PASTE_MAX_LINES = 5;
const PASTE_MAX_CHARS = 1000;

// Soft upper cap: a paste longer than this many lines is truncated to the first
// PASTE_CAP_LINES before it's chipped/sent, with the drop surfaced on the chip. This is
// a guardrail against an accidental giant paste blowing the agent's context/cost — well
// under the 64 MB WebSocket frame, which is the hard transport ceiling. Line-based only:
// a pathological single very-long line still rides up to the frame limit.
const PASTE_CAP_LINES = 50000;

function isLargePaste(s: string): boolean {
  return s.length > PASTE_MAX_CHARS || s.split("\n").length > PASTE_MAX_LINES;
}

// Truncate a paste to the line cap. Returns the kept text and how many lines were
// dropped (0 when under the cap).
function capPaste(s: string): { text: string; dropped: number } {
  const lines = s.split("\n");
  if (lines.length <= PASTE_CAP_LINES) return { text: s, dropped: 0 };
  return {
    text: lines.slice(0, PASTE_CAP_LINES).join("\n"),
    dropped: lines.length - PASTE_CAP_LINES,
  };
}

// A collapsed stand-in for one large pasted block. Collapsed by default (just a one-line
// summary); Expand reveals a scrollable preview, ✕ drops it before send. When the paste
// was truncated at the line cap, a warning notes how many lines were dropped.
function PasteChip({
  text,
  dropped,
  onRemove,
}: {
  text: string;
  dropped: number;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const lines = text.split("\n").length;
  return (
    <div className="rounded border border-zinc-700 bg-zinc-800/60 text-xs">
      <div className="flex items-center gap-2 px-2 py-1.5">
        <span aria-hidden>📄</span>
        <span className="text-zinc-200">Pasted text</span>
        <span className="text-zinc-500">
          · {lines} {lines === 1 ? "line" : "lines"}
        </span>
        <span className="rounded bg-zinc-700 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-zinc-300">
          Pasted
        </span>
        {dropped > 0 ? (
          <span
            title={`Truncated to the first ${PASTE_CAP_LINES.toLocaleString()} lines`}
            className="rounded bg-amber-950 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-amber-300"
          >
            ⚠ truncated · {dropped.toLocaleString()} dropped
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse pasted text" : "Expand pasted text"}
          className="ml-auto rounded px-1.5 py-0.5 text-zinc-400 hover:text-zinc-100"
        >
          {expanded ? "Collapse ▲" : "Expand ▼"}
        </button>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove pasted text"
          className="rounded px-1 text-zinc-400 hover:text-zinc-100"
        >
          ×
        </button>
      </div>
      {expanded ? (
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap border-t border-zinc-700 px-2 py-1.5 font-mono text-[11px] text-zinc-300">
          {text}
        </pre>
      ) : null}
    </div>
  );
}

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
  const [pastes, setPastes] = useState<{ id: number; text: string; dropped: number }[]>([]);
  const [dragging, setDragging] = useState(false);
  // Monotonic key source for paste chips, so removing one never re-keys the others
  // (index keys would let a child chip's expanded state bleed onto its neighbor).
  const nextPasteId = useRef(0);

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

  // Accept image drops anywhere the window sees the event. The visual affordance
  // (below) is deliberately localized to the composer: rendered artifacts are
  // sandboxed iframes that swallow drag events, so a drop over them never reaches this
  // window handler and leaks to the browser (it navigates to the file). Rather than
  // fight that, we point users at the composer — the region guaranteed to catch a drop
  // — instead of dimming the whole screen as if it were all droppable.
  // The overlay only shows for file drags (not text/link drags), and clears when the
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

  // Escape hatch for a stuck overlay: a file drag that ends outside the window (dropped
  // on another app, or cancelled at the OS level) fires neither drop nor a window
  // dragleave, so `dragging` can hang true. Esc always clears it (harmless no-op
  // otherwise; no preventDefault, so other Esc handlers still fire). A ✕ on the overlay
  // covers the same for mouse users.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setDragging(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function handlePaste(e: React.ClipboardEvent) {
    // Images first (a folder selection Cmd-C'd carries several) — an image paste never
    // also carries the kind of text we'd want to chip.
    const files = Array.from(e.clipboardData.items)
      .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
      .map((it) => it.getAsFile())
      .filter((f): f is File => f !== null);
    if (files.length > 0) {
      e.preventDefault();
      for (const file of files) attachImageFile(file);
      return;
    }
    // A large plain-text paste becomes a collapsed chip instead of flooding the box.
    // Smaller pastes fall through to the textarea's default behavior.
    const pasted = e.clipboardData.getData("text/plain");
    if (isLargePaste(pasted)) {
      e.preventDefault();
      const { text: capped, dropped } = capPaste(pasted);
      setPastes((prev) => [
        ...prev,
        { id: nextPasteId.current++, text: capped, dropped },
      ]);
    }
  }

  function send() {
    if (busy) return;
    // Stitch the typed prompt and any chipped pastes back into one message body, in
    // visual order (prompt first, then each paste), separated by blank lines.
    const body = [text.trim(), ...pastes.map((p) => p.text)]
      .filter((part) => part.length > 0)
      .join("\n\n");
    if (!body && images.length === 0) return;
    onSend(body, images.length ? images : undefined);
    setText("");
    setImages([]);
    setPastes([]);
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
    <form onSubmit={submit} className="relative flex shrink-0 flex-col gap-2 p-2">
      {dragging ? (
        <>
          {/* A very subtle full-window tint signals drag mode is active without
              advertising the whole screen as a drop target. pointer-events-none so it
              never intercepts the real window-level drop handler. */}
          <div className="pointer-events-none fixed inset-0 z-40 bg-zinc-950/20" />
          {/* The honest target: highlighted over the composer, the one region where a
              drop is guaranteed to land. */}
          <div className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded border-2 border-dashed border-emerald-400/80 bg-emerald-400/10">
            <div className="pointer-events-auto flex items-center gap-2 rounded border border-emerald-500/50 bg-zinc-900 px-3 py-1.5 text-sm text-emerald-100">
              <span>Drop screenshot here</span>
              <button
                type="button"
                onClick={() => setDragging(false)}
                aria-label="Dismiss"
                title="Dismiss (Esc)"
                className="-mr-1 rounded px-1 leading-none text-emerald-300/70 hover:text-emerald-100"
              >
                ✕
              </button>
            </div>
          </div>
        </>
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
      {pastes.length > 0 ? (
        <div className="flex flex-col gap-2">
          {pastes.map((p) => (
            <PasteChip
              key={p.id}
              text={p.text}
              dropped={p.dropped}
              onRemove={() => setPastes((prev) => prev.filter((q) => q.id !== p.id))}
            />
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
            disabled={!text.trim() && images.length === 0 && pastes.length === 0}
            className="absolute bottom-2 right-2 rounded border border-zinc-700 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
          >
            Send
          </button>
        )}
      </div>
    </form>
  );
}
