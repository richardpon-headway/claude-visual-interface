import type { Finding, Range } from "./viewState";

// A line-range decoration to draw on the open file: a finding's anchored lines,
// or a view-state highlight_range. Kept Monaco-free so it's unit-testable; the
// CodePane maps these to Monaco decorations at render time.
export type LineDecoration = {
  startLine: number;
  endLine: number;
  kind: "finding" | "highlight";
  severity: string | null;
};

export function toDecorations(
  file: string,
  findings: Finding[],
  highlights: Record<string, Range[]>,
): LineDecoration[] {
  const decorations: LineDecoration[] = [];

  for (const finding of findings) {
    // Only findings anchored to a line range in *this* file can be drawn on the
    // code; un-anchored findings stay in the side panel only.
    if (finding.file === file && finding.anchor) {
      decorations.push({
        startLine: finding.anchor.range.start,
        endLine: finding.anchor.range.end,
        kind: "finding",
        severity: finding.severity,
      });
    }
  }

  for (const range of highlights[file] ?? []) {
    decorations.push({ startLine: range.start, endLine: range.end, kind: "highlight", severity: null });
  }

  return decorations;
}
