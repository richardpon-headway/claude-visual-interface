import type { Finding, OpenFile } from "./viewState";

// The file the primary (pane 0) code pane should show. A finding the user
// clicked wins over the daemon-pushed open file, so clicking a finding always
// opens its file (scrolled to its anchor, when it has one).
export function primaryOpenFile(
  activeFinding: Finding | null,
  viewOpen0: OpenFile | undefined,
): OpenFile | undefined {
  if (activeFinding) {
    return { file: activeFinding.file, range: activeFinding.anchor?.range ?? null };
  }
  return viewOpen0;
}
