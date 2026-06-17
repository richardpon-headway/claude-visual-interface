// Client mirror of the daemon's per-surface state. The daemon↔browser types are
// hand-mirrored (the plan's accepted tradeoff vs an end-to-end-TS stack); keep
// these in sync with daemon/view_state.py.

// One conversation segment (mirrors daemon ActivityEntry): the user's prompt,
// Claude's text, a tool call, a run result, an inline artifact (kind "artifact":
// `html` is the page, `text` its title), or a file diff (kind "file": `text` is the
// path, `diff` the unified diff).
export type ActivityEntry = {
  kind: string;
  text: string;
  html?: string | null;
  summary?: string | null; // for a user prompt: its generated outline-rail label
  diff?: string | null; // for a file segment (text=path): the unified diff vs the base
};

// Transient view state — mirrors daemon ViewState (store.snapshot): the conversation
// transcript plus an in-flight "thinking" flag.
export type ViewState = {
  surface: string;
  activity: ActivityEntry[]; // the conversation, oldest-first
  thinking: boolean; // an agent turn is in flight (drives the thinking indicator)
};

// The full client state for a surface: the live view, the session's run status
// (running / ready / error; null until known), and its title (null until known;
// auto-generated for chats).
export type SurfaceState = {
  view: ViewState;
  status: string | null;
  title: string | null;
};

// Messages the daemon pushes over the WebSocket. `snapshot` carries a full
// ViewState on connect; the rest are incremental events.
export type WsMessage =
  | { type: "snapshot"; surface: string; payload: ViewState }
  | { type: "activity"; surface: string; payload: ActivityEntry }
  | { type: "status"; surface: string; payload: { status: string } }
  | { type: "thinking"; surface: string; payload: { active: boolean } }
  | { type: "title"; surface: string; payload: { title: string } }
  | { type: "prompt_summary"; surface: string; payload: { index: number; text: string } };

const MESSAGE_TYPES = [
  "snapshot",
  "activity",
  "status",
  "thinking",
  "title",
  "prompt_summary",
];

export function emptyViewState(surface: string): ViewState {
  return {
    surface,
    activity: [],
    thinking: false,
  };
}

export function emptySurface(surface: string): SurfaceState {
  return { view: emptyViewState(surface), status: null, title: null };
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
