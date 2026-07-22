// Client mirror of the daemon's per-surface state. The daemon↔browser types are
// hand-mirrored (the plan's accepted tradeoff vs an end-to-end-TS stack); keep
// these in sync with daemon/view_state.py.

// One conversation segment (mirrors daemon ActivityEntry): the user's prompt,
// Claude's text, a tool call, a run result, or an inline artifact (kind "artifact":
// `html` is the page, `text` its title).
// One option in an AskUserQuestion question, and a question itself (mirrors the
// AskUserQuestion tool's `input.questions` shape).
// `preview` is a self-contained HTML fragment rendered inline in the picker (in a
// sandboxed iframe) as the option's rich body, beside its Select button. When absent,
// the option falls back to a plain label (+ optional description) row.
export type AskOption = { label: string; description?: string; preview?: string };
export type AskQuestion = {
  question: string;
  header?: string;
  multiSelect?: boolean;
  options: AskOption[];
};

export type ActivityEntry = {
  kind: string;
  text: string;
  html?: string | null;
  summary?: string | null; // for a user prompt: its generated outline-rail label
  background?: boolean; // segment belongs to an agent-initiated (background-task) turn
  ask_id?: string | null; // for an "ask" entry: the tool-use id, echoed back to answer
  questions?: AskQuestion[] | null; // for an "ask" entry: the picker's questions
  answer?: string | null; // for an "ask" entry: the chosen value, once answered
};

// Transient view state — mirrors daemon ViewState (store.snapshot): the conversation
// transcript and an in-flight "thinking" flag.
export type ViewState = {
  surface: string;
  activity: ActivityEntry[]; // the conversation, oldest-first
  thinking: boolean; // an agent turn is in flight (drives the thinking indicator)
  session_output_tokens: number; // running session token totals across every LLM call
  session_input_tokens: number;
};

// The full client state for a surface: the live view, its title (null until known;
// auto-generated for chats), and the starred flag.
export type SurfaceState = {
  view: ViewState;
  title: string | null;
  starred: boolean; // seeded over HTTP; no live WebSocket event in v1
};

// Messages the daemon pushes over the WebSocket. `snapshot` carries a full
// ViewState on connect; the rest are incremental events.
export type WsMessage =
  | { type: "snapshot"; surface: string; payload: ViewState }
  | { type: "activity"; surface: string; payload: ActivityEntry }
  | { type: "thinking"; surface: string; payload: { active: boolean } }
  | { type: "title"; surface: string; payload: { title: string } }
  | { type: "prompt_summary"; surface: string; payload: { index: number; text: string } }
  | { type: "tokens"; surface: string; payload: { output: number; input: number } }
  | { type: "answer"; surface: string; payload: { id: string; answer: string } };

const MESSAGE_TYPES = [
  "snapshot",
  "activity",
  "thinking",
  "title",
  "prompt_summary",
  "tokens",
  "answer",
];

export function emptyViewState(surface: string): ViewState {
  return {
    surface,
    activity: [],
    thinking: false,
    session_output_tokens: 0,
    session_input_tokens: 0,
  };
}

export function emptySurface(surface: string): SurfaceState {
  return { view: emptyViewState(surface), title: null, starred: false };
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
    case "thinking":
      return { ...state, view: { ...state.view, thinking: msg.payload.active } };
    case "title":
      return { ...state, title: msg.payload.title };
    case "tokens":
      return {
        ...state,
        view: {
          ...state.view,
          session_output_tokens: msg.payload.output,
          session_input_tokens: msg.payload.input,
        },
      };
    case "answer": {
      // Lock the matching picker to its chosen value (rides the snapshot on reload).
      const { id, answer } = msg.payload;
      const activity = state.view.activity.map((e) =>
        e.kind === "ask" && e.ask_id === id ? { ...e, answer } : e,
      );
      return { ...state, view: { ...state.view, activity } };
    }
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
