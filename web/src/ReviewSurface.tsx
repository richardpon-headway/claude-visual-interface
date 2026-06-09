import { useState } from "react";

import { CodePane } from "./CodePane";
import { FindingsPanel } from "./FindingsPanel";
import { primaryOpenFile } from "./findingFocus";
import { useSurfaceSocket } from "./useSurfaceSocket";
import type { Finding, Range } from "./viewState";

export function ReviewSurface({ surface }: { surface: string }) {
  const { view, findings } = useSurfaceSocket(surface);
  const paneIndexes = Array.from({ length: view.panes }, (_, i) => i);
  const allFindings = Object.values(findings);

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
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Left: code panes. Right: findings (the conversation lands here later). */}
        <main className="flex min-h-0 flex-1">
          {paneIndexes.map((i) => (
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
          ))}
        </main>
        <FindingsPanel
          findings={findings}
          activeId={activeFinding?.id ?? null}
          onSelect={selectFinding}
        />
      </div>

      <footer className="border-t border-zinc-800 px-4 py-1 text-xs text-zinc-500">
        {view.diff ? `diff: ${view.diff.a} vs ${view.diff.b} · ` : ""}
        highlights: {Object.values(view.highlights).reduce((n, ranges) => n + ranges.length, 0)}
      </footer>
    </div>
  );
}
