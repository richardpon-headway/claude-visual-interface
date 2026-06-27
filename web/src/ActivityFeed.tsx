import { useEffect, useRef, useState } from "react";

import { Markdown } from "./Markdown";
import type { ActivityEntry, AskQuestion } from "./viewState";

// Prose, tool lines, and pickers stay in a readable centered column; artifacts
// (model-rendered HTML) break out to the full transcript width instead.
const PROSE = "mx-auto w-full max-w-3xl";

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
function ArtifactBlock({ title, html }: { title: string; html: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number>();
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const iframe = ref.current;
    if (!iframe) return;
    setWide(false); // re-decide width for new content (measured at the narrow width)
    let observer: ResizeObserver | undefined;
    // Measure the RENDERED height. getBoundingClientRect() reflects CSS `zoom`
    // (artifacts scale themselves to 1.25 to match the app's UI scale); scrollHeight
    // does not, so using it alone under-sizes the frame and the content scrolls
    // internally. Take the max so we never under-size regardless of zoom.
    const measureHeight = (doc: Document) =>
      setHeight(
        Math.ceil(
          Math.max(
            doc.documentElement.getBoundingClientRect().height,
            doc.documentElement.scrollHeight,
          ),
        ),
      );
    const sync = () => {
      const doc = iframe.contentDocument;
      if (!doc) return;
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
      srcDoc={html}
      title={title || "artifact"}
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

// A pick per question: a single chosen option index (or null), or a sorted list of
// indices for a multi-select question.
type Pick = number | number[] | null;

function formatAnswer(questions: AskQuestion[], picks: Pick[]): string {
  // One readable line per question so the agent can map answers back to questions.
  return questions
    .map((q, qi) => {
      const label = q.header || q.question;
      const p = picks[qi];
      const chosen = q.multiSelect
        ? (p as number[]).map((i) => q.options[i].label).join(", ")
        : q.options[p as number].label;
      return `${label}: ${chosen}`;
    })
    .join("\n");
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
  const [cursor, setCursor] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  // Flat (question, option) positions so ↑↓ can move across every option in the entry.
  const positions: { qi: number; oi: number }[] = [];
  questions.forEach((q, qi) => q.options.forEach((_, oi) => positions.push({ qi, oi })));

  const answered = (p: Pick[], qi: number) =>
    questions[qi].multiSelect ? (p[qi] as number[]).length > 0 : p[qi] !== null;
  const allAnswered = (p: Pick[]) => questions.every((_, qi) => answered(p, qi));
  const hasMulti = questions.some((q) => q.multiSelect);

  // The locked/answered value: the persisted answer (rides the snapshot on reload) or,
  // optimistically, what we just submitted this session.
  const persistedAnswer =
    typeof entry.answer === "string" && entry.answer.length > 0 ? entry.answer : null;
  const shownAnswer = persistedAnswer ?? (submitted ? formatAnswer(questions, picks) : null);
  const locked = shownAnswer !== null;

  function submit(p: Pick[]) {
    if (locked || !allAnswered(p) || !onAnswer || !entry.ask_id) return;
    onAnswer(entry.ask_id, formatAnswer(questions, p));
    setSubmitted(true);
  }

  // Single-select sends as soon as every question is answered; multi-select waits for
  // an explicit Enter / Submit (so you can toggle several before committing).
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
      if (!hasMulti) submit(np);
    }
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
        if (allAnswered(picks)) submit(picks);
        else if (!questions[pos.qi].multiSelect) selectAt(pos.qi, pos.oi);
      } else if (/^[1-9]$/.test(e.key) && Number(e.key) <= questions[pos.qi].options.length) {
        e.preventDefault();
        selectAt(pos.qi, Number(e.key) - 1);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, cursor, picks]); // eslint-disable-line react-hooks/exhaustive-deps

  if (questions.length === 0) {
    return (
      <li className={`${PROSE} text-xs text-zinc-500`}>
        <span className="font-mono text-sky-400/80">{entry.text}</span>
      </li>
    );
  }

  const selectedCount = picks.reduce<number>(
    (n, p) => n + (Array.isArray(p) ? p.length : p !== null ? 1 : 0),
    0,
  );

  const answerLines = shownAnswer ? shownAnswer.split("\n") : [];

  return (
    <li className={`${PROSE} space-y-2`}>
      {questions.map((q, qi) => {
        const prefix = `${q.header || q.question}: `;
        const line = answerLines[qi] ?? "";
        const chosenText = line.startsWith(prefix) ? line.slice(prefix.length) : line;
        return (
        <div key={qi} className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3">
          {q.header ? (
            <span className="mb-2 inline-block rounded bg-amber-900 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
              {q.header}
            </span>
          ) : null}
          <div className="mb-2 text-sm font-medium text-zinc-100">{q.question}</div>
          {locked ? (
            <div className="rounded-lg border border-amber-800 bg-amber-950 px-3 py-2 text-sm text-amber-100">
              {chosenText}
            </div>
          ) : (
          <div className="space-y-1">
            {q.options.map((o, oi) => {
              const isCursor =
                active && positions[cursor]?.qi === qi && positions[cursor]?.oi === oi;
              const chosen = q.multiSelect
                ? (picks[qi] as number[]).includes(oi)
                : picks[qi] === oi;
              return (
                <button
                  key={oi}
                  type="button"
                  disabled={submitted}
                  onClick={() => {
                    setCursor(positions.findIndex((p) => p.qi === qi && p.oi === oi));
                    selectAt(qi, oi);
                  }}
                  className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2 text-left ${
                    chosen
                      ? "border-amber-800 bg-amber-950"
                      : isCursor
                        ? "border-zinc-700 bg-zinc-900"
                        : "border-transparent hover:bg-zinc-900"
                  } ${submitted && !chosen ? "opacity-40" : ""}`}
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
          )}
        </div>
        );
      })}
      {locked ? (
        <div className="text-xs text-emerald-400">✓ answered</div>
      ) : hasMulti ? (
        <button
          type="button"
          disabled={!allAnswered(picks)}
          onClick={() => submit(picks)}
          className="rounded border border-amber-900 bg-amber-950 px-3 py-1 text-xs text-amber-300 hover:bg-amber-900 disabled:opacity-40"
        >
          Submit{selectedCount ? ` ${selectedCount}` : ""} ↵
        </button>
      ) : null}
    </li>
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
  // the outline rail can scroll to it.
  if (entry.kind === "user") {
    return (
      <li id={promptId} className={`${PROSE} flex justify-end scroll-mt-4`}>
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-zinc-800 px-4 py-3 text-sm text-zinc-100">
          {entry.text}
        </div>
      </li>
    );
  }
  // The assistant's answer renders as markdown, full width.
  if (entry.kind === "text") {
    return (
      <li className={`${PROSE} text-sm text-zinc-200`}>
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
        <ArtifactBlock title={entry.text} html={entry.html ?? ""} />
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
