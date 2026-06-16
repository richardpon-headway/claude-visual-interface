import { useState } from "react";

import { ActivityFeed } from "./ActivityFeed";
import { ArtifactPane } from "./ArtifactPane";
import { ChatInput } from "./ChatInput";
import { CodePane } from "./CodePane";
import { FindingsPanel } from "./FindingsPanel";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { primaryOpenFile } from "./findingFocus";
import { useSurfaceSocket } from "./useSurfaceSocket";
import type { Finding, Range } from "./viewState";

function StatusChip({ status }: { status: string | null }) {
  const cls =
    status === "ready"
      ? "bg-emerald-900 text-emerald-200"
      : status === "error"
        ? "bg-red-900 text-red-200"
        : status === "running"
          ? "bg-sky-900 text-sky-200"
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

export function ReviewSurface({ surface }: { surface: string }) {
  const [{ view, findings, status }, sendMessage] = useSurfaceSocket(surface);
  const paneIndexes = Array.from({ length: view.panes }, (_, i) => i);
  const allFindings = Object.values(findings);
  const openCount = allFindings.filter((f) => !f.disposition).length;

  const [activeFinding, setActiveFinding] = useState<Finding | null>(null);
  // The reveal carries a nonce so re-clicking the same finding (unchanged range)
  // still re-fires the scroll-to effect in CodePane.
  const [reveal, setReveal] = useState<{ range: Range; nonce: number } | null>(null);

  function selectFinding(finding: Finding) {
    setActiveFinding(finding);
    const anchor = finding.anchor;
    if (anchor) {
      setReveal((prev) => ({ range: anchor.range, nonce: (prev?.nonce ?? 0) + 1 }));
    } else {
      setReveal(null);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2 text-sm">
        <a href="/" className="text-zinc-400 hover:text-zinc-100">
          ← sessions
        </a>
        <span className="font-semibold">Claude Visual Interface</span>
        <span className="text-zinc-500">surface: {surface}</span>
        <span className="ml-auto flex items-center gap-2">
          <StatusChip status={status} />
          <span className="text-zinc-500">
            {allFindings.length} findings · {openCount} open
          </span>
        </span>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left: an HTML artifact when one is set, else the code panes. Right:
            findings + the conversation. */}
        <main className="flex min-h-0 flex-1">
          {view.artifact ? (
            <div className="min-w-0 flex-1">
              <ArtifactPane artifact={view.artifact} />
            </div>
          ) : (
            paneIndexes.map((i) => (
              <div key={i} className="min-w-0 flex-1 border-r border-zinc-800 last:border-r-0">
                <CodePane
                  surface={surface}
                  openFile={
                    i === 0 ? primaryOpenFile(activeFinding, view.open["0"]) : view.open[String(i)]
                  }
                  findings={allFindings}
                  highlights={view.highlights}
                  reveal={i === 0 ? reveal : undefined}
                />
              </div>
            ))
          )}
        </main>
        {/* Right: the conversation — activity/transcript over findings, chat box below. */}
        <aside className="flex w-96 min-w-0 flex-col border-l border-zinc-800">
          <ActivityFeed activity={view.activity} />
          <FindingsPanel
            findings={findings}
            activeId={activeFinding?.id ?? null}
            onSelect={selectFinding}
          />
          <ThinkingIndicator active={view.thinking} />
          <ChatInput onSend={sendMessage} />
        </aside>
      </div>

      <footer className="border-t border-zinc-800 px-4 py-1 text-xs text-zinc-500">
        {view.diff ? `diff: ${view.diff.a} vs ${view.diff.b} · ` : ""}
        highlights: {Object.values(view.highlights).reduce((n, ranges) => n + ranges.length, 0)}
      </footer>
    </div>
  );
}
