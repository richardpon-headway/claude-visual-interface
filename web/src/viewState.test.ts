import { describe, expect, it } from "vitest";

import { applyMessage, emptySurface, emptyViewState, parseMessage } from "./viewState";
import type { ViewState } from "./viewState";

describe("parseMessage", () => {
  it("parses known message types", () => {
    expect(parseMessage(JSON.stringify({ type: "activity", surface: "s", payload: {} }))?.type).toBe(
      "activity",
    );
    expect(parseMessage(JSON.stringify({ type: "thinking", surface: "s", payload: {} }))?.type).toBe(
      "thinking",
    );
    expect(
      parseMessage(JSON.stringify({ type: "background_working", surface: "s", payload: {} }))?.type,
    ).toBe("background_working");
    expect(parseMessage(JSON.stringify({ type: "title", surface: "s", payload: {} }))?.type).toBe(
      "title",
    );
  });

  it("rejects malformed JSON and unknown types", () => {
    expect(parseMessage("{nope")).toBeNull();
    expect(parseMessage(JSON.stringify({ type: "explode" }))).toBeNull();
  });
});

describe("applyMessage", () => {
  it("emptyViewState starts blank", () => {
    expect(emptyViewState("s")).toEqual({
      surface: "s",
      activity: [],
      thinking: false,
      background_working: false,
      session_output_tokens: 0,
      session_input_tokens: 0,
      queue: [],
    });
  });

  it("replaces the view on a snapshot", () => {
    const incoming: ViewState = {
      surface: "s",
      activity: [{ kind: "text", text: "buffered" }],
      thinking: true,
      background_working: true,
      session_output_tokens: 0,
      session_input_tokens: 0,
      queue: [],
    };
    let state = emptySurface("s");
    state = applyMessage(state, { type: "snapshot", surface: "s", payload: incoming });
    expect(state.view.activity).toEqual([{ kind: "text", text: "buffered" }]);
    expect(state.view.thinking).toBe(true);
    expect(state.view.background_working).toBe(true);
  });

  it("defaults the queue to [] on a snapshot that omits it (old daemon)", () => {
    const legacy = {
      surface: "s",
      activity: [],
      thinking: false,
      background_working: false,
      session_output_tokens: 0,
      session_input_tokens: 0,
      // no `queue` field — a daemon that predates it
    } as unknown as ViewState;
    let state = emptySurface("s");
    state = applyMessage(state, { type: "snapshot", surface: "s", payload: legacy });
    expect(state.view.queue).toEqual([]);
  });

  it("replaces the queue on a pending_queue event", () => {
    let state = emptySurface("s");
    state = applyMessage(state, {
      type: "pending_queue",
      surface: "s",
      payload: { items: [{ id: "a", text: "one" }, { id: "b", text: "two" }] },
    });
    expect(state.view.queue).toEqual([{ id: "a", text: "one" }, { id: "b", text: "two" }]);
    // A later empty event clears it (every pending item skipped / started running).
    state = applyMessage(state, { type: "pending_queue", surface: "s", payload: { items: [] } });
    expect(state.view.queue).toEqual([]);
  });

  it("appends activity entries in arrival order", () => {
    let state = emptySurface("s");
    state = applyMessage(state, { type: "activity", surface: "s", payload: { kind: "text", text: "reviewing" } });
    state = applyMessage(state, { type: "activity", surface: "s", payload: { kind: "tool", text: "Bash" } });
    expect(state.view.activity).toEqual([
      { kind: "text", text: "reviewing" },
      { kind: "tool", text: "Bash" },
    ]);
  });

  it("flips the thinking flag", () => {
    let state = applyMessage(emptySurface("s"), { type: "thinking", surface: "s", payload: { active: true } });
    expect(state.view.thinking).toBe(true);
    state = applyMessage(state, { type: "thinking", surface: "s", payload: { active: false } });
    expect(state.view.thinking).toBe(false);
  });

  it("flips the background_working flag independently of thinking", () => {
    let state = applyMessage(emptySurface("s"), {
      type: "background_working",
      surface: "s",
      payload: { active: true },
    });
    expect(state.view.background_working).toBe(true);
    expect(state.view.thinking).toBe(false);
    state = applyMessage(state, { type: "background_working", surface: "s", payload: { active: false } });
    expect(state.view.background_working).toBe(false);
  });

  it("sets the title", () => {
    const state = applyMessage(emptySurface("s"), {
      type: "title",
      surface: "s",
      payload: { title: "Fix the parser" },
    });
    expect(state.title).toBe("Fix the parser");
  });

  it("sets the running session token totals", () => {
    const state = applyMessage(emptySurface("s"), {
      type: "tokens",
      surface: "s",
      payload: { output: 1234, input: 56789 },
    });
    expect(state.view.session_output_tokens).toBe(1234);
    expect(state.view.session_input_tokens).toBe(56789);
  });

  it("locks the matching picker to its answer", () => {
    let state = emptySurface("s");
    state = applyMessage(state, {
      type: "activity",
      surface: "s",
      payload: { kind: "ask", text: "pick", ask_id: "ask-9", questions: [] },
    });
    state = applyMessage(state, {
      type: "answer",
      surface: "s",
      payload: { id: "ask-9", answer: "Approach: Custom modal" },
    });
    expect(state.view.activity[0].answer).toBe("Approach: Custom modal");
  });
});
