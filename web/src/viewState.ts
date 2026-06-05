// Client mirror of the daemon's per-surface view state (daemon/view_state.py).
// The daemon↔browser types are hand-mirrored (the plan's accepted tradeoff vs
// an end-to-end-TS stack); keep this in sync with the daemon dataclasses.

export type Range = { start: number; end: number };
export type OpenFile = { file: string; range: Range | null };
export type Diff = { a: string; b: string };
export type Selection = { file: string; range: Range };

export type ViewState = {
  surface: string;
  panes: number;
  open: Record<string, OpenFile>; // pane index (as string) -> open file
  highlights: Record<string, Range[]>; // file -> highlighted ranges
  diff: Diff | null;
  selection: Selection | null; // what the user has selected on the left pane
};

// Messages the daemon pushes over the WebSocket. `snapshot` carries a full
// ViewState (sent on connect); the rest are incremental view-control events.
export type WsMessage =
  | { type: "snapshot"; surface: string; payload: ViewState }
  | { type: "open_code"; surface: string; payload: { file: string; range: Range | null; pane: number } }
  | { type: "split_pane"; surface: string; payload: { n: number } }
  | { type: "highlight_range"; surface: string; payload: { file: string; range: Range } }
  | { type: "show_diff"; surface: string; payload: { a: string; b: string } };

const MESSAGE_TYPES = ["snapshot", "open_code", "split_pane", "highlight_range", "show_diff"];

export function emptyViewState(surface: string): ViewState {
  return { surface, panes: 1, open: {}, highlights: {}, diff: null, selection: null };
}

// Parse a raw WebSocket payload into a known message, or null if it doesn't
// look like one. Guards the trust boundary so a malformed frame can't crash
// the reducer (rather than blindly casting JSON.parse output to WsMessage).
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

export function applyMessage(state: ViewState, msg: WsMessage): ViewState {
  switch (msg.type) {
    case "snapshot":
      return msg.payload;
    case "open_code": {
      const { file, range, pane } = msg.payload;
      return { ...state, open: { ...state.open, [String(pane)]: { file, range } } };
    }
    case "split_pane": {
      const n = msg.payload.n;
      const open = Object.fromEntries(
        Object.entries(state.open).filter(([pane]) => Number(pane) < n),
      );
      return { ...state, panes: n, open };
    }
    case "highlight_range": {
      const { file, range } = msg.payload;
      const existing = state.highlights[file] ?? [];
      return { ...state, highlights: { ...state.highlights, [file]: [...existing, range] } };
    }
    case "show_diff":
      return { ...state, diff: { a: msg.payload.a, b: msg.payload.b } };
  }
}
