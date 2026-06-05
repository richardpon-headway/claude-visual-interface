import { CodePane } from "./CodePane";
import { useSurfaceSocket } from "./useSurfaceSocket";

// Routing (/s/<uuid>) lands in a later phase; for now the surface id is the
// URL path (or "default" at the root).
function surfaceFromLocation(): string {
  return window.location.pathname.replace(/^\/+/, "") || "default";
}

export function App() {
  const surface = surfaceFromLocation();
  const view = useSurfaceSocket(surface);
  const paneIndexes = Array.from({ length: view.panes }, (_, i) => i);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2 text-sm">
        <span className="font-semibold">Claude Visual Interface</span>
        <span className="text-zinc-500">surface: {surface}</span>
      </header>

      <main className="flex min-h-0 flex-1">
        {paneIndexes.map((i) => (
          <div key={i} className="min-w-0 flex-1 border-r border-zinc-800 last:border-r-0">
            <CodePane openFile={view.open[String(i)]} />
          </div>
        ))}
      </main>

      <footer className="border-t border-zinc-800 px-4 py-1 text-xs text-zinc-500">
        {view.diff ? `diff: ${view.diff.a} vs ${view.diff.b} · ` : ""}
        highlights: {Object.values(view.highlights).reduce((n, ranges) => n + ranges.length, 0)}
      </footer>
    </div>
  );
}
