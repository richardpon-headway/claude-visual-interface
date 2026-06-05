// Client mirror of the daemon's per-surface state. The daemon↔browser types are
// hand-mirrored (the plan's accepted tradeoff vs an end-to-end-TS stack); keep
// these in sync with daemon/view_state.py and daemon/findings.py.

export type Range = { start: number; end: number };
export type OpenFile = { file: string; range: Range | null };
export type Diff = { a: string; b: string };
export type Selection = { file: string; range: Range };

// Transient view state — mirrors daemon ViewState (store.snapshot).
export type ViewState = {
  surface: string;
  panes: number;
  open: Record<string, OpenFile>; // pane index (as string) -> open file
  highlights: Record<string, Range[]>; // file -> highlighted ranges
  diff: Diff | null;
  selection: Selection | null;
};

// A persisted, code-anchored review finding (mirrors a daemon/findings.py row).
export type Finding = {
  id: string;
  session_id: string;
  file: string;
  anchor: { snippet: string; range: Range } | null;
  severity: string | null;
  title: string;
  body: string;
  suggested_patch: string | null;
  source_lens: string | null;
  actions: string[] | null;
  disposition: string | null;
};

// The full client state for a surface: the live view plus its findings (keyed by id).
export type SurfaceState = {
  view: ViewState;
  findings: Record<string, Finding>;
};

// Messages the daemon pushes over the WebSocket. `snapshot` carries a full
// ViewState on connect; the rest are incremental view-control or finding events.
export type WsMessage =
  | { type: "snapshot"; surface: string; payload: ViewState }
  | { type: "open_code"; surface: string; payload: { file: string; range: Range | null; pane: number } }
  | { type: "split_pane"; surface: string; payload: { n: number } }
  | { type: "highlight_range"; surface: string; payload: { file: string; range: Range } }
  | { type: "show_diff"; surface: string; payload: { a: string; b: string } }
  | { type: "finding"; surface: string; payload: Finding }
  | { type: "disposition"; surface: string; payload: { finding_id: string; value: string } };

const MESSAGE_TYPES = [
  "snapshot",
  "open_code",
  "split_pane",
  "highlight_range",
  "show_diff",
  "finding",
  "disposition",
];

export function emptyViewState(surface: string): ViewState {
  return { surface, panes: 1, open: {}, highlights: {}, diff: null, selection: null };
}

export function emptySurface(surface: string): SurfaceState {
  return { view: emptyViewState(surface), findings: {} };
}

// Parse a raw WebSocket payload into a known message, or null if it doesn't look
// like one — guards the trust boundary so a malformed frame can't crash the reducer.
export function parseMessage(raw: string): WsMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof (value as { type: unknown }).type === "string" &&
    MESSAGE_TYPES.includes((value as { type: string }).type)
  ) {
    return value as WsMessage;
  }
  return null;
}

export function applyMessage(state: SurfaceState, msg: WsMessage): SurfaceState {
  switch (msg.type) {
    case "snapshot":
      return { ...state, view: msg.payload };
    case "open_code": {
      const { file, range, pane } = msg.payload;
      return { ...state, view: { ...state.view, open: { ...state.view.open, [String(pane)]: { file, range } } } };
    }
    case "split_pane": {
      const n = msg.payload.n;
      const open = Object.fromEntries(
        Object.entries(state.view.open).filter(([pane]) => Number(pane) < n),
      );
      return { ...state, view: { ...state.view, panes: n, open } };
    }
    case "highlight_range": {
      const { file, range } = msg.payload;
      const existing = state.view.highlights[file] ?? [];
      return {
        ...state,
        view: { ...state.view, highlights: { ...state.view.highlights, [file]: [...existing, range] } },
      };
    }
    case "show_diff":
      return { ...state, view: { ...state.view, diff: { a: msg.payload.a, b: msg.payload.b } } };
    case "finding":
      return { ...state, findings: { ...state.findings, [msg.payload.id]: msg.payload } };
    case "disposition": {
      const existing = state.findings[msg.payload.finding_id];
      if (!existing) return state;
      return {
        ...state,
        findings: { ...state.findings, [existing.id]: { ...existing, disposition: msg.payload.value } },
      };
    }
  }
}
