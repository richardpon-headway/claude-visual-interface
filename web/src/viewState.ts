// Client mirror of the daemon's per-surface state. The daemon↔browser types are
// hand-mirrored (the plan's accepted tradeoff vs an end-to-end-TS stack); keep
// these in sync with daemon/view_state.py and daemon/findings.py.

export type Range = { start: number; end: number };
export type OpenFile = { file: string; range: Range | null };
export type Diff = { a: string; b: string };
// A self-contained HTML page rendered on the left pane (mirrors daemon Artifact).
export type Artifact = { html: string; title: string | null };
export type Selection = { file: string; range: Range };
// One conversation segment (mirrors daemon ActivityEntry): the user's prompt,
// Claude's text, a tool call, a run result, or an inline artifact (kind "artifact":
// `html` carries the page, `text` its title).
export type ActivityEntry = {
  kind: string;
  text: string;
  html?: string | null;
  summary?: string | null; // for a user prompt: its generated outline-rail label
  diff?: string | null; // for a file segment (text=path): the unified diff vs the base
};

// Transient view state — mirrors daemon ViewState (store.snapshot).
export type ViewState = {
  surface: string;
  panes: number;
  open: Record<string, OpenFile>; // pane index (as string) -> open file
  highlights: Record<string, Range[]>; // file -> highlighted ranges
  diff: Diff | null;
  artifact: Artifact | null; // an HTML page shown instead of the code views, or null
  selection: Selection | null;
  activity: ActivityEntry[]; // buffered review narration, oldest-first
  thinking: boolean; // an agent turn is in flight (drives the thinking indicator)
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

// The full client state for a surface: the live view plus its findings (keyed by
// id), the session's run status (running / ready / error; null until known), and
// its title (null until known; auto-generated for chats).
export type SurfaceState = {
  view: ViewState;
  findings: Record<string, Finding>;
  status: string | null;
  title: string | null;
};

// Messages the daemon pushes over the WebSocket. `snapshot` carries a full
// ViewState on connect; the rest are incremental view-control or finding events.
export type WsMessage =
  | { type: "snapshot"; surface: string; payload: ViewState }
  | { type: "open_code"; surface: string; payload: { file: string; range: Range | null; pane: number } }
  | { type: "split_pane"; surface: string; payload: { n: number } }
  | { type: "highlight_range"; surface: string; payload: { file: string; range: Range } }
  | { type: "show_diff"; surface: string; payload: { a: string; b: string } }
  | { type: "render_html"; surface: string; payload: { html: string; title: string | null } }
  | { type: "finding"; surface: string; payload: Finding }
  | { type: "disposition"; surface: string; payload: { finding_id: string; value: string } }
  | { type: "activity"; surface: string; payload: ActivityEntry }
  | { type: "status"; surface: string; payload: { status: string } }
  | { type: "thinking"; surface: string; payload: { active: boolean } }
  | { type: "title"; surface: string; payload: { title: string } }
  | { type: "prompt_summary"; surface: string; payload: { index: number; text: string } };

const MESSAGE_TYPES = [
  "snapshot",
  "open_code",
  "split_pane",
  "highlight_range",
  "show_diff",
  "render_html",
  "finding",
  "disposition",
  "activity",
  "status",
  "thinking",
  "title",
  "prompt_summary",
];

export function emptyViewState(surface: string): ViewState {
  return {
    surface,
    panes: 1,
    open: {},
    highlights: {},
    diff: null,
    artifact: null,
    selection: null,
    activity: [],
    thinking: false,
  };
}

export function emptySurface(surface: string): SurfaceState {
  return { view: emptyViewState(surface), findings: {}, status: null, title: null };
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
      // Showing code clears any artifact, mirroring the daemon store.
      return {
        ...state,
        view: {
          ...state.view,
          open: { ...state.view.open, [String(pane)]: { file, range } },
          artifact: null,
        },
      };
    }
    case "split_pane": {
      const n = msg.payload.n;
      const open = Object.fromEntries(
        Object.entries(state.view.open).filter(([pane]) => Number(pane) < n),
      );
      return { ...state, view: { ...state.view, panes: n, open, artifact: null } };
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
    case "render_html":
      return { ...state, view: { ...state.view, artifact: msg.payload } };
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
    case "activity":
      return { ...state, view: { ...state.view, activity: [...state.view.activity, msg.payload] } };
    case "status":
      return { ...state, status: msg.payload.status };
    case "thinking":
      return { ...state, view: { ...state.view, thinking: msg.payload.active } };
    case "title":
      return { ...state, title: msg.payload.title };
    case "prompt_summary": {
      // Attach the summary to the index-th user prompt (the rail's `prompt-N`).
      const { index, text } = msg.payload;
      let n = -1;
      const activity = state.view.activity.map((e) => {
        if (e.kind !== "user") return e;
        n += 1;
        return n === index ? { ...e, summary: text } : e;
      });
      return { ...state, view: { ...state.view, activity } };
    }
  }
}
