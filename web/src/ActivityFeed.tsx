import { useState } from "react";

import { Markdown } from "./Markdown";
import type { ActivityEntry } from "./viewState";

// A model-authored HTML page, rendered inline as a sandboxed iframe block with a
// collapse/expand toggle (sandboxed iframes can't self-size).
function ArtifactBlock({ title, html }: { title: string; html: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="overflow-hidden rounded border border-zinc-800">
      <div className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-900 px-3 py-1 font-mono text-xs text-zinc-400">
        <span className="truncate">{title || "artifact"}</span>
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="ml-auto rounded border border-zinc-700 px-1.5 text-zinc-300 hover:bg-zinc-800"
        >
          {expanded ? "collapse" : "expand"}
        </button>
      </div>
      <iframe
        className={`w-full border-0 bg-white ${expanded ? "h-[80vh]" : "h-96"}`}
        sandbox=""
        srcDoc={html}
        title={title || "artifact"}
      />
    </div>
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

function ActivityRow({ entry, promptId }: { entry: ActivityEntry; promptId?: string }) {
  // Your prompts read as right-aligned bubbles; each carries a stable anchor id so
  // the outline rail can scroll to it.
  if (entry.kind === "user") {
    return (
      <li id={promptId} className="flex justify-end scroll-mt-4">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-zinc-800 px-3.5 py-2 text-sm text-zinc-100">
          {entry.text}
        </div>
      </li>
    );
  }
  // The assistant's answer renders as markdown, full width.
  if (entry.kind === "text") {
    return (
      <li className="text-sm text-zinc-200">
        <Markdown>{entry.text}</Markdown>
      </li>
    );
  }
  // A model-rendered HTML page, inline in the flow.
  if (entry.kind === "artifact") {
    return (
      <li>
        <ArtifactBlock title={entry.text} html={entry.html ?? ""} />
      </li>
    );
  }
  // Tool calls and run results are compact, dim one-liners.
  const label = kindLabel(entry.kind);
  return (
    <li className="text-xs text-zinc-500">
      {label ? (
        <span className="mr-2 rounded bg-zinc-800/70 px-1.5 py-0.5 font-mono text-[10px] uppercase text-zinc-400">
          {label}
        </span>
      ) : null}
      <span className={entry.kind === "tool" ? "font-mono text-sky-400/80" : ""}>{entry.text}</span>
    </li>
  );
}

// The conversation transcript: your prompts, the assistant's markdown answers, and
// compact tool/result lines, in arrival order. The parent owns scrolling and width.
export function ActivityFeed({ activity }: { activity: ActivityEntry[] }) {
  if (activity.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-zinc-500">Ask anything to get started.</div>
    );
  }
  // A successful run result is implied by the answer above it; hide it as noise.
  // Failures (error / stopped / API error / …) still surface.
  const shown = activity.filter((e) => !(e.kind === "result" && e.text === "success"));
  let userCount = 0;
  return (
    <ul className="space-y-3">
      {shown.map((entry, i) => {
        const promptId = entry.kind === "user" ? `prompt-${userCount++}` : undefined;
        return <ActivityRow key={i} entry={entry} promptId={promptId} />;
      })}
    </ul>
  );
}
