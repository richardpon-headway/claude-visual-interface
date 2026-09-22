import { useEffect, useMemo, useRef, useState } from "react";

import { formatGroupAnswer, isAddressed, parseGroupAnswer, pickSet, type Pick } from "./askAnswer";
import { ErrorBoundary } from "./ErrorBoundary";
import { Markdown } from "./Markdown";
import { PasteChip } from "./PasteChip";
import type { ActivityEntry } from "./viewState";

// Prose, tool lines, and pickers stay in a readable centered column; artifacts
// (model-rendered HTML) break out to the full transcript width instead.
const PROSE = "mx-auto w-full max-w-3xl";

// A full-viewport overlay showing one screenshot at up to its stored size. Click the
// scrim or the close button, or press Escape, to dismiss; body scroll is locked while
// open. The image is capped to the viewport (object-contain) so a large stored copy
// fits without overflow. Reuses the app's existing scrim+Esc modal pattern.
function Lightbox({ name, onClose }: { name: string; onClose: () => void }) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6"
      onClick={onClose}
    >
      <img
        src={`/screenshots/${name}`}
        alt="screenshot"
        onClick={(e) => e.stopPropagation()}
        className="max-h-full max-w-full rounded object-contain shadow-2xl"
      />
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="absolute right-4 top-4 rounded-full bg-zinc-800/80 px-3 py-1 text-sm text-zinc-200 hover:bg-zinc-700"
      >
        Esc ✕
      </button>
    </div>
  );
}

// A persisted user screenshot, served by the daemon at /screenshots/<name>. If the file
// was deleted (manual cleanup), the <img> errors and we swap to a muted placeholder so
// the transcript degrades gracefully instead of showing a broken image. Click a thumbnail
// to open it full-size in a Lightbox overlay.
function HistoryImage({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  if (failed) {
    return (
      <div className="flex h-24 w-32 items-center justify-center rounded border border-zinc-700 bg-zinc-900 px-2 text-center text-xs text-zinc-500">
        screenshot no longer available
      </div>
    );
  }
  return (
    <>
      <img
        src={`/screenshots/${name}`}
        alt="screenshot"
        onError={() => setFailed(true)}
        onClick={() => setExpanded(true)}
        className="max-h-64 max-w-xs cursor-zoom-in rounded border border-zinc-700 object-contain"
      />
      {expanded ? <Lightbox name={name} onClose={() => setExpanded(false)} /> : null}
    </>
  );
}

// A model-authored HTML page, rendered inline as a sandboxed iframe sized to its
// full content height — always shown in full, no expand/collapse. The frame stays
// script-free: we add allow-same-origin (NOT allow-scripts) only so the parent can
// read the content's size and grow the frame to fit, including after late
// image/font reflow.
//
// Width: the frame starts at the chat-text column width (TEXT_COL) and is left-aligned
// to that column's left edge. If the content can't fit at that width (it overflows
// horizontally), the frame widens rightward up to WIDE_CAP — so narrow artifacts line
// up with the surrounding text, and wide ones (big tables) get the extra room.
const TEXT_COL = "48rem"; // matches the chat column (Tailwind max-w-3xl)
const WIDE_CAP = "64rem"; // most a wide artifact may grow to

// A model-authored page is dropped into a sealed iframe that inherits nothing from the
// app: not the app's 125% UI scale (so it renders ~20% small) and not the dark surface
// (so an unstyled page falls back to browser-default white — a jarring flash inside the
// dark app). We fix both here, in one place, so no author has to remember to:
//   - zoom every artifact to 1.25 to match the app scale (authors must NOT set their own
//     zoom now, or the two would multiply); and
//   - render on the dark surface by default. A UI mockup that needs its own colors opts
//     out with data-theme="light" on the root <html>, and we leave its background alone.
// The dark background uses !important so it reliably wins for any page WITHOUT the marker
// (the "dark unless marker" contract); text color is a soft default the page can override.
function withCviDefaults(html: string): string {
  const isLight = /data-theme\s*=\s*["']light["']/i.test(html);
  const surface =
    getComputedStyle(document.documentElement).getPropertyValue("--cvi-surface").trim() ||
    "#09090b";
  const darkRules = isLight
    ? ""
    : `html{color:#e4e4e7;}html,body{background:${surface} !important;}`;
  const style = `<style id="cvi-artifact-defaults">html{zoom:1.25;}${darkRules}</style>`;
  // Land it late in <head> when there is one (wins source-order ties); otherwise prepend.
  return /<\/head>/i.test(html)
    ? html.replace(/<\/head>/i, `${style}</head>`)
    : style + html;
}

// Size a sandboxed iframe to its content. The frame stays script-free: allow-same-origin
// (NOT allow-scripts) lets the parent read the content's size and grow the frame to fit,
// including after late image/font reflow. `wide` reports whether the content overflowed
// the narrow (text-column) width and wants more room — artifacts act on it; inline
// previews (fixed to their card's width) ignore it.
function useIframeAutoSize(html: string) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number>();
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const iframe = ref.current;
    if (!iframe) return;
    setWide(false); // re-decide width for new content (measured at the narrow width)
    let observer: ResizeObserver | undefined;
    // Measure the RENDERED height. getBoundingClientRect() reflects CSS `zoom`
    // (frames scale themselves to 1.25 to match the app's UI scale); scrollHeight
    // does not, so using it alone under-sizes the frame and the content scrolls
    // internally. Take the max so we never under-size regardless of zoom.
    const measureHeight = (doc: Document) => {
      // A freshly-created iframe exposes a contentDocument before the browser has
      // parsed srcDoc, so documentElement can still be null here — guard it or the
      // getBoundingClientRect read throws and (with no boundary) blanks the app.
      const el = doc.documentElement;
      if (!el) return;
      setHeight(Math.ceil(Math.max(el.getBoundingClientRect().height, el.scrollHeight)));
    };
    const sync = () => {
      const doc = iframe.contentDocument;
      if (!doc || !doc.documentElement) return; // not parsed yet; the load event re-runs sync
      measureHeight(doc);
      // Decide width once, while the frame is still at the narrow (text-column) width:
      // if the content overflows horizontally it wants more room, so switch to wide.
      // scrollWidth/clientWidth are both in the frame's own CSS px, so `zoom` cancels.
      const el = doc.documentElement;
      if (el.scrollWidth > el.clientWidth + 1) setWide(true);
      if (!observer) {
        // The observer only keeps height in sync (reflow, late image/font load); it
        // never re-decides width, which would oscillate once the frame has widened.
        observer = new ResizeObserver(() => {
          const d = iframe.contentDocument;
          if (d) measureHeight(d);
        });
        observer.observe(el);
      }
    };
    iframe.addEventListener("load", sync);
    sync(); // srcDoc may have already settled before the listener attached
    return () => {
      iframe.removeEventListener("load", sync);
      observer?.disconnect();
    };
  }, [html]);

  return { ref, height, wide };
}

// A model-authored HTML page, rendered inline as a sandboxed iframe sized to its full
// content height — always shown in full, no expand/collapse.
//
// Width: the frame starts at the chat-text column width (TEXT_COL) and is left-aligned
// to that column's left edge. If the content can't fit at that width (it overflows
// horizontally), the frame widens rightward up to WIDE_CAP — so narrow artifacts line
// up with the surrounding text, and wide ones (big tables) get the extra room.
function ArtifactBlock({ title, html }: { title: string; html: string }) {
  const doc = useMemo(() => withCviDefaults(html), [html]);
  const { ref, height, wide } = useIframeAutoSize(html);

  return (
    <iframe
      ref={ref}
      className="block border-0 bg-transparent"
      style={{
        height: height != null ? `${height}px` : "24rem",
        // Left edge pinned to the chat column's left edge; narrow = centered on that
        // column (matches the text), wide = grows rightward without overflowing.
        marginLeft: `max(0px, calc((100% - ${TEXT_COL}) / 2))`,
        width: wide
          ? `min(${WIDE_CAP}, calc((100% + ${TEXT_COL}) / 2))`
          : `min(${TEXT_COL}, 100%)`,
      }}
      sandbox="allow-same-origin"
      srcDoc={doc}
      title={title || "artifact"}
    />
  );
}

// An AskUserQuestion option's rich `preview`, rendered inline in the picker as a
// sandboxed, script-free iframe that fills its card's width and grows to its content
// height. Same dark-surface + scale defaults as an artifact; unlike an artifact it
// never breaks out wider than the card (the picker owns the layout).
function OptionPreview({ html }: { html: string }) {
  const doc = useMemo(() => withCviDefaults(html), [html]);
  const { ref, height } = useIframeAutoSize(html);

  return (
    <iframe
      ref={ref}
      className="block w-full border-0 bg-transparent"
      style={{ height: height != null ? `${height}px` : "6rem" }}
      sandbox="allow-same-origin"
      srcDoc={doc}
      title="option"
    />
  );
}

function kindLabel(kind: string): string {
  switch (kind) {
    case "tool":
      return "tool";
    case "result":
      return "result";
    default:
      return "";
  }
}

// An AskUserQuestion call, rendered as an interactive picker — one card per question.
// Selecting sends the answer as the next message (the only feasible path with the
// built-in tool). Falls back to a plain line when the structured payload isn't
// available (e.g. rehydrated after a restart).
function AskPicker({
  entry,
  onAnswer,
  isLatest,
}: {
  entry: ActivityEntry;
  onAnswer?: (askId: string, answer: string) => void;
  isLatest: boolean;
}) {
  const questions = entry.questions ?? [];
  const [picks, setPicks] = useState<Pick[]>(() =>
    questions.map((q) => (q.multiSelect ? [] : null)),
  );
  // Per-question free text: null = the affordance isn't opened; a string (incl. "") =
  // opened. `customs` is a custom answer (an inline "Other"); `notes` is a question to
  // the agent. Both are independent of the options and of each other.
  const [customs, setCustoms] = useState<(string | null)[]>(() => questions.map(() => null));
  const [notes, setNotes] = useState<(string | null)[]>(() => questions.map(() => null));
  const [cursor, setCursor] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  // Flat (question, option) positions so ↑↓ can move across every option in the entry.
  const positions: { qi: number; oi: number }[] = [];
  questions.forEach((q, qi) => q.options.forEach((_, oi) => positions.push({ qi, oi })));

  // A question is "addressed" (satisfies the submit gate) by a pick, a custom answer,
  // OR a question — any combination. The whole group still submits at once.
  const allAddressed = (p: Pick[], c: (string | null)[], n: (string | null)[]) =>
    questions.every((q, qi) => isAddressed(q, p[qi], c[qi], n[qi]));
  const hasMulti = questions.some((q) => q.multiSelect);
  // Any free-text field opened → the group commits via the explicit Send button (a
  // keystroke can't be "the last answer" while text is in flight). Once a field has been
  // opened this session the button stays put even if it's later closed, so toggling a
  // field off can't strand a picked group with no way to send.
  const [everOpened, setEverOpened] = useState(false);
  const anyTextOpen = customs.some((c) => c !== null) || notes.some((n) => n !== null);
  const usesButton = hasMulti || anyTextOpen || everOpened;

  // The locked/answered value: the persisted answer (rides the snapshot on reload) or,
  // optimistically, what we just submitted this session (re-derived from current state).
  const persistedAnswer =
    typeof entry.answer === "string" && entry.answer.length > 0 ? entry.answer : null;
  const shownAnswer =
    persistedAnswer ?? (submitted ? formatGroupAnswer(questions, picks, customs, notes) : null);
  const locked = shownAnswer !== null;
  // Per-question responses reconstructed from the answer string, for the locked render.
  const answered = shownAnswer ? parseGroupAnswer(questions, shownAnswer) : null;

  function submit(p: Pick[], c: (string | null)[], n: (string | null)[]) {
    if (locked || !allAddressed(p, c, n) || !onAnswer || !entry.ask_id) return;
    onAnswer(entry.ask_id, formatGroupAnswer(questions, p, c, n));
    setSubmitted(true);
  }

  // Single-select auto-sends once the group is fully addressed — but only on the pure
  // pick-only fast path (no multi-select, no text field opened). Otherwise the explicit
  // Send button commits.
  function selectAt(qi: number, oi: number) {
    if (locked) return;
    const np = [...picks];
    if (questions[qi].multiSelect) {
      const set = new Set(np[qi] as number[]);
      set.has(oi) ? set.delete(oi) : set.add(oi);
      np[qi] = [...set].sort((a, b) => a - b);
      setPicks(np);
    } else {
      np[qi] = oi;
      setPicks(np);
      if (!usesButton) submit(np, customs, notes);
    }
  }

  // Open a free-text affordance (null → "") or close it (→ null, discarding its text).
  function toggleCustom(qi: number) {
    setEverOpened(true);
    setCustoms((c) => c.map((v, i) => (i === qi ? (v === null ? "" : null) : v)));
  }
  function toggleNote(qi: number) {
    setEverOpened(true);
    setNotes((n) => n.map((v, i) => (i === qi ? (v === null ? "" : null) : v)));
  }

  const active = isLatest && !locked && questions.length > 0;
  useEffect(() => {
    if (!active) return;
    function onKey(e: KeyboardEvent) {
      const ae = document.activeElement;
      // The composer owns the keyboard while it's focused — don't hijack typing.
      if (ae && (ae.tagName === "TEXTAREA" || ae.tagName === "INPUT")) return;
      const pos = positions[cursor];
      if (!pos) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(c + 1, positions.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (e.key === " " && questions[pos.qi].multiSelect) {
        e.preventDefault();
        selectAt(pos.qi, pos.oi);
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (allAddressed(picks, customs, notes)) submit(picks, customs, notes);
        else if (!questions[pos.qi].multiSelect) selectAt(pos.qi, pos.oi);
      } else if (/^[1-9]$/.test(e.key) && Number(e.key) <= questions[pos.qi].options.length) {
        e.preventDefault();
        selectAt(pos.qi, Number(e.key) - 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, cursor, picks, customs, notes]); // eslint-disable-line react-hooks/exhaustive-deps

  if (questions.length === 0) {
    return (
      <li className={`${PROSE} text-xs text-zinc-500`}>
        <span className="font-mono text-sky-400/80">{entry.text}</span>
      </li>
    );
  }

  const groupLabel = questions.length === 1 ? "1 question" : `${questions.length} questions`;

  // All questions from one AskUserQuestion call live inside a single bordered group so
  // they read as one connected decision that submits at once — not N separate cards.
  return (
    <li className={PROSE}>
      <div className="rounded-2xl border border-zinc-700 bg-zinc-950/40 px-4 py-4">
        <div className="mb-3 flex items-baseline gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
            ◇ {groupLabel}
          </span>
          {!locked ? (
            <span className="text-[11px] text-zinc-600">· answer all to continue</span>
          ) : null}
        </div>
        <div className="space-y-3">
      {questions.map((q, qi) => {
        // Which option indices are the committed answer for this question — reconstructed
        // from the answer string (which, once submitted, round-trips from the current
        // picks, and after a reload is all that survives). Once locked we keep every
        // option rendered and use this to highlight the chosen one(s) rather than
        // collapsing to just the pick — so the alternatives stay readable for context.
        // Before submit, reflect the live picks so selections show immediately; once
        // locked, use the parsed committed answer (which is all that survives a reload).
        const chosenSet = locked
          ? (answered?.[qi]?.chosen ?? new Set<number>())
          : pickSet(picks[qi]);
        return (
        <div key={qi} className="rounded-lg border border-zinc-800/70 bg-zinc-950 px-4 py-3">
          {q.header ? (
            <span className="mb-2 inline-block rounded bg-amber-900 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
              {q.header}
            </span>
          ) : null}
          <div className="mb-2 text-sm font-medium text-zinc-100">{q.question}</div>
          <div className="space-y-2">
            {q.options.map((o, oi) => {
              const isCursor =
                active && positions[cursor]?.qi === qi && positions[cursor]?.oi === oi;
              const chosen = chosenSet.has(oi);
              // When locked, non-chosen options stay on screen but dimmed so the chosen
              // answer reads as the commitment while the alternatives remain legible.
              const dim = locked && !chosen;
              const onSelect = () => {
                setCursor(positions.findIndex((p) => p.qi === qi && p.oi === oi));
                selectAt(qi, oi);
              };
              // Rich option: the preview renders in a sandboxed card, with a native
              // Select button pinned to the card's bottom edge (items-end). The button —
              // trusted app chrome, outside the sandbox — owns the click; nothing
              // clickable lives inside the frame. The label is still what's sent as the
              // answer (formatGroupAnswer), so the preview should lead with it.
              if (o.preview) {
                return (
                  <div
                    key={oi}
                    className={`flex items-end gap-3 rounded-lg border px-3 py-2 ${
                      chosen
                        ? "border-amber-800 bg-amber-950"
                        : isCursor
                          ? "border-zinc-700 bg-zinc-900"
                          : "border-zinc-800"
                    } ${dim ? "opacity-60" : ""}`}
                  >
                    <div className="min-w-0 flex-1 overflow-hidden">
                      <OptionPreview html={o.preview} />
                    </div>
                    <button
                      type="button"
                      disabled={locked}
                      aria-label={`Select ${o.label}`}
                      onClick={onSelect}
                      className={`shrink-0 rounded-md border px-3 py-1.5 text-xs font-semibold ${
                        chosen
                          ? "border-amber-700 bg-amber-800 text-amber-100"
                          : "border-amber-900 bg-amber-950 text-amber-300 hover:bg-amber-900"
                      } disabled:opacity-40`}
                    >
                      {locked
                        ? chosen
                          ? "✓ Selected"
                          : "Not selected"
                        : q.multiSelect
                          ? chosen
                            ? "[x] Selected"
                            : "Select"
                          : chosen
                            ? "✓ Selected"
                            : `Select ${oi + 1}`}
                    </button>
                  </div>
                );
              }
              // Plain option: the whole row is one button (label + optional description).
              return (
                <button
                  key={oi}
                  type="button"
                  disabled={locked}
                  onClick={onSelect}
                  className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left ${
                    chosen
                      ? "border-amber-800 bg-amber-950"
                      : isCursor
                        ? "border-zinc-700 bg-zinc-900"
                        : locked
                          ? "border-zinc-800"
                          : "border-transparent hover:bg-zinc-900"
                  } ${dim ? "opacity-60" : ""}`}
                >
                  {q.multiSelect ? (
                    <span
                      className={`mt-0.5 shrink-0 font-mono text-sm ${chosen ? "text-amber-400" : "text-zinc-600"}`}
                    >
                      {chosen ? "[x]" : "[ ]"}
                    </span>
                  ) : (
                    <span
                      className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-xs font-semibold ${chosen ? "bg-amber-800 text-amber-100" : "bg-zinc-800 text-zinc-300"}`}
                    >
                      {oi + 1}
                    </span>
                  )}
                  <span className="min-w-0">
                    <span className="block text-sm text-zinc-100">{o.label}</span>
                    {o.description ? (
                      <span className="mt-0.5 block text-xs text-zinc-500">{o.description}</span>
                    ) : null}
                  </span>
                </button>
              );
            })}
          </div>
          {/* Free-text affordances — both always available, independent of the options
              and of each other: a custom answer (an inline "Other") and a question to
              the agent (defer this one for discussion). */}
          {!locked ? (
            <>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => toggleCustom(qi)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] ${
                    customs[qi] !== null
                      ? "border-emerald-800 bg-emerald-950 text-emerald-300"
                      : "border-dashed border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
                  }`}
                >
                  {customs[qi] !== null ? "− custom answer" : "+ custom answer"}
                </button>
                <button
                  type="button"
                  onClick={() => toggleNote(qi)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] ${
                    notes[qi] !== null
                      ? "border-sky-800 bg-sky-950 text-sky-300"
                      : "border-dashed border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-200"
                  }`}
                >
                  {notes[qi] !== null ? "− ask about this" : "+ ask about this"}
                </button>
              </div>
              {customs[qi] !== null ? (
                <textarea
                  aria-label={`Custom answer for ${q.header || q.question}`}
                  value={customs[qi] ?? ""}
                  onChange={(e) =>
                    setCustoms((c) => c.map((v, i) => (i === qi ? e.target.value : v)))
                  }
                  placeholder="Write your own answer…"
                  className="mt-2 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-500 focus:outline-none"
                  rows={2}
                />
              ) : null}
              {notes[qi] !== null ? (
                <textarea
                  aria-label={`Question about ${q.header || q.question}`}
                  value={notes[qi] ?? ""}
                  onChange={(e) =>
                    setNotes((n) => n.map((v, i) => (i === qi ? e.target.value : v)))
                  }
                  placeholder="Ask the agent about this instead of deciding now…"
                  className="mt-2 w-full rounded-md border border-sky-900 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-sky-700 focus:outline-none"
                  rows={2}
                />
              ) : null}
            </>
          ) : (
            <>
              {answered?.[qi]?.custom ? (
                <div className="mt-2 rounded-md border border-emerald-900 bg-emerald-950/40 px-3 py-2">
                  <span className="block text-[10px] font-semibold uppercase tracking-wide text-emerald-500">
                    Custom answer
                  </span>
                  <span className="mt-0.5 block whitespace-pre-wrap text-sm text-zinc-200">
                    {answered[qi].custom}
                  </span>
                </div>
              ) : null}
              {answered?.[qi]?.question ? (
                <div className="mt-2 rounded-md border border-sky-900 bg-sky-950/40 px-3 py-2">
                  <span className="block text-[10px] font-semibold uppercase tracking-wide text-sky-400">
                    Question
                  </span>
                  <span className="mt-0.5 block whitespace-pre-wrap text-sm text-zinc-200">
                    {answered[qi].question}
                  </span>
                </div>
              ) : null}
            </>
          )}
        </div>
        );
      })}
        </div>
        {locked ? (
          <div className="mt-3 text-xs text-emerald-400">✓ answered</div>
        ) : usesButton ? (
          <button
            type="button"
            disabled={!allAddressed(picks, customs, notes)}
            onClick={() => submit(picks, customs, notes)}
            className="mt-3 rounded border border-amber-900 bg-amber-950 px-3 py-1 text-xs text-amber-300 hover:bg-amber-900 disabled:opacity-40"
          >
            Send group ↵
          </button>
        ) : null}
      </div>
    </li>
  );
}

// A small marker on segments from an agent-initiated (background-task) turn, so they
// read as "the agent reacting to a finished task" rather than a reply to your prompt.
function BackgroundTag() {
  return (
    <span className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-violet-300/80">
      <span aria-hidden>↳</span> background
    </span>
  );
}

// The user's typed prompt, right-aligned. Always shown in full — never collapsed. A
// large paste rides separately (entry.pastes) and renders as its own collapsible chip
// below, so the typed prompt itself never needs truncating.
function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex max-w-[85%] flex-col items-end gap-1">
      <div className="whitespace-pre-wrap rounded-2xl bg-zinc-800 px-4 py-3 text-sm text-zinc-100">
        {text}
      </div>
    </div>
  );
}

function ActivityRow({
  entry,
  promptId,
  onAnswer,
  isLatestAsk,
}: {
  entry: ActivityEntry;
  promptId?: string;
  onAnswer?: (askId: string, answer: string) => void;
  isLatestAsk?: boolean;
}) {
  // Your prompts read as right-aligned bubbles; each carries a stable anchor id so
  // the outline rail can scroll to it. A large paste renders as its own collapsible chip
  // below the typed text; attached screenshots render as thumbnails below that. A turn
  // with only pastes / only images shows just those (no empty text bubble).
  if (entry.kind === "user") {
    const images = entry.images ?? [];
    const pastes = entry.pastes ?? [];
    return (
      <li id={promptId} className={`${PROSE} flex flex-col items-end gap-2 scroll-mt-4`}>
        {entry.text ? <UserBubble text={entry.text} /> : null}
        {pastes.length > 0 ? (
          <div className="flex w-full max-w-[85%] flex-col gap-2">
            {pastes.map((p, i) => (
              <PasteChip key={i} text={p} />
            ))}
          </div>
        ) : null}
        {images.length > 0 ? (
          <div className="flex max-w-[85%] flex-wrap justify-end gap-2">
            {images.map((name) => (
              <HistoryImage key={name} name={name} />
            ))}
          </div>
        ) : null}
      </li>
    );
  }
  // The assistant's answer renders as markdown, full width. A background-turn answer
  // (the agent reacting to a finished task, not a reply to a prompt) is tagged and
  // dimmed so it doesn't read as an answer to something you typed.
  if (entry.kind === "text") {
    return (
      <li className={`${PROSE} text-sm ${entry.background ? "text-zinc-400" : "text-zinc-200"}`}>
        {entry.background ? <BackgroundTag /> : null}
        <Markdown>{entry.text}</Markdown>
      </li>
    );
  }
  // An AskUserQuestion picker.
  if (entry.kind === "ask") {
    return <AskPicker entry={entry} onAnswer={onAnswer} isLatest={isLatestAsk ?? false} />;
  }
  // A model-rendered HTML page, inline in the flow. Full-width row so the frame can
  // align to the chat column and widen rightward; ArtifactBlock owns its own width.
  if (entry.kind === "artifact") {
    return (
      <li className="w-full">
        <ErrorBoundary
          fallback={
            <div
              className={`${PROSE} rounded-lg border border-zinc-800 bg-zinc-950 px-4 py-3 text-xs text-zinc-500`}
            >
              Couldn't render this artifact{entry.text ? `: ${entry.text}` : ""}.
            </div>
          }
        >
          <ArtifactBlock title={entry.text} html={entry.html ?? ""} />
        </ErrorBoundary>
      </li>
    );
  }
  // Tool calls and run results are compact, dim one-liners.
  const label = kindLabel(entry.kind);
  return (
    <li className={`${PROSE} text-xs text-zinc-500`}>
      {label ? (
        <span className="mr-2 rounded bg-zinc-800/70 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-400">
          {label}
        </span>
      ) : null}
      <span className={entry.kind === "tool" ? "font-mono text-sky-400/80" : ""}>{entry.text}</span>
    </li>
  );
}

// One agent turn's tool calls, collapsed into a single bar instead of a tall stack of
// one-liners. While the turn is in flight it shows a live count and the latest call. Once
// the turn settles it rests as a quiet, non-expandable count.
function ToolBar({ tools, inProgress }: { tools: ActivityEntry[]; inProgress: boolean }) {
  const count = tools.length;
  const latest = tools[count - 1]?.text ?? "";
  return (
    <li className={PROSE}>
      <div
        className={`rounded-lg border px-3 py-2 ${
          inProgress ? "border-sky-800/70 bg-sky-950/40" : "border-sky-900/30 bg-sky-950/20"
        }`}
      >
        <div className="flex items-center gap-2.5 text-xs">
          {inProgress ? (
            <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-sky-400 shadow-[0_0_6px_#38bdf8]" />
          ) : null}
          <span className="shrink-0 font-semibold tabular-nums text-sky-300">
            {count} tool call{count === 1 ? "" : "s"}
          </span>
          {inProgress && latest ? (
            <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-sky-400/80">
              {latest}
            </span>
          ) : null}
        </div>
      </div>
    </li>
  );
}

// The conversation transcript: your prompts, the assistant's markdown answers, and
// compact tool/result lines, in arrival order. The parent owns scrolling and width.
// Tool calls collapse per turn into a single ToolBar so a long search run doesn't bury
// the conversation; the bar lands where the turn's first tool call would have.
export function ActivityFeed({
  activity,
  thinking = false,
  onAnswer,
}: {
  activity: ActivityEntry[];
  thinking?: boolean;
  onAnswer?: (askId: string, answer: string) => void;
}) {
  if (activity.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-zinc-500">Ask anything to get started.</div>
    );
  }
  // A successful run result is implied by the answer above it; hide it as noise.
  // Failures (error / stopped / API error / …) still surface.
  const shown = activity.filter((e) => !(e.kind === "result" && e.text === "success"));
  // Only the last unanswered picker captures the keyboard, so stray keys can't drive
  // an old picker further up the transcript.
  let lastAsk = -1;
  shown.forEach((e, i) => {
    if (e.kind === "ask" && !e.answer) lastAsk = i;
  });

  // Group tool calls by turn (a user prompt starts a turn). All of a turn's tool calls
  // collapse into one bar, rendered at the position of the turn's first tool call; the
  // rest are suppressed. The bar is "in progress" only for the active (last) turn while
  // the agent is still thinking.
  const turnOf: number[] = [];
  let turn = -1;
  shown.forEach((e) => {
    if (e.kind === "user") turn += 1;
    turnOf.push(turn);
  });
  const toolsByTurn = new Map<number, ActivityEntry[]>();
  const firstToolIndexByTurn = new Map<number, number>();
  shown.forEach((e, i) => {
    if (e.kind !== "tool") return;
    const t = turnOf[i];
    const arr = toolsByTurn.get(t);
    if (arr) arr.push(e);
    else toolsByTurn.set(t, [e]);
    if (!firstToolIndexByTurn.has(t)) firstToolIndexByTurn.set(t, i);
  });
  const lastToolTurn = toolsByTurn.size ? Math.max(...toolsByTurn.keys()) : -1;
  // The active turn is the latest one overall. A bar is "in progress" only when its
  // turn is both the last one to run a tool AND the current turn — otherwise a finished
  // turn's bar would re-light (showing its last command) while the next prompt is
  // thinking but hasn't called a tool yet.
  const currentTurn = turn;

  let userCount = 0;
  return (
    <ul className="space-y-3">
      {shown.map((entry, i) => {
        if (entry.kind === "tool") {
          // Only the turn's first tool call renders the bar; the rest fold into it.
          if (firstToolIndexByTurn.get(turnOf[i]) !== i) return null;
          const tools = toolsByTurn.get(turnOf[i]) ?? [entry];
          return (
            <ToolBar
              key={i}
              tools={tools}
              inProgress={thinking && turnOf[i] === lastToolTurn && lastToolTurn === currentTurn}
            />
          );
        }
        const promptId = entry.kind === "user" ? `prompt-${userCount++}` : undefined;
        return (
          <ActivityRow
            key={i}
            entry={entry}
            promptId={promptId}
            onAnswer={onAnswer}
            isLatestAsk={i === lastAsk}
          />
        );
      })}
    </ul>
  );
}
