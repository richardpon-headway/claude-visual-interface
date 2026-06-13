import type { Artifact } from "./viewState";

// Renders a model-authored HTML page on the left pane. The HTML is rendered in a
// sandboxed iframe so the document's own browsing context isolates its global CSS
// from the app (and vice versa). The empty `sandbox` attribute is the security
// boundary: no scripts, no network — static HTML/CSS/SVG only.
export function ArtifactPane({ artifact }: { artifact: Artifact }) {
  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-zinc-800 px-3 py-1 font-mono text-xs text-zinc-400">
        {artifact.title ?? "artifact"}
      </div>
      <iframe
        className="min-h-0 flex-1 border-0 bg-white"
        sandbox=""
        srcDoc={artifact.html}
        title={artifact.title ?? "artifact"}
      />
    </div>
  );
}
