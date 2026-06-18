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
    expect(parseMessage(JSON.stringify({ type: "title", surface: "s", payload: {} }))?.type).toBe(
      "title",
    );
    expect(
      parseMessage(JSON.stringify({ type: "prompt_summary", surface: "s", payload: {} }))?.type,
    ).toBe("prompt_summary");
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
      session_output_tokens: 0,
      session_input_tokens: 0,
    });
  });

  it("replaces the view on a snapshot", () => {
    const incoming: ViewState = {
      surface: "s",
      activity: [{ kind: "text", text: "buffered" }],
      thinking: true,
      session_output_tokens: 0,
      session_input_tokens: 0,
    };
    let state = emptySurface("s");
    state = applyMessage(state, { type: "snapshot", surface: "s", payload: incoming });
    expect(state.view.activity).toEqual([{ kind: "text", text: "buffered" }]);
    expect(state.view.thinking).toBe(true);
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

  it("sets the status", () => {
    const state = applyMessage(emptySurface("s"), { type: "status", surface: "s", payload: { status: "ready" } });
    expect(state.status).toBe("ready");
  });

  it("flips the thinking flag", () => {
    let state = applyMessage(emptySurface("s"), { type: "thinking", surface: "s", payload: { active: true } });
    expect(state.view.thinking).toBe(true);
    state = applyMessage(state, { type: "thinking", surface: "s", payload: { active: false } });
    expect(state.view.thinking).toBe(false);
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

  it("attaches a prompt summary to the matching user prompt", () => {
    let state = emptySurface("s");
    state = applyMessage(state, { type: "activity", surface: "s", payload: { kind: "user", text: "first" } });
    state = applyMessage(state, { type: "activity", surface: "s", payload: { kind: "text", text: "answer" } });
    state = applyMessage(state, { type: "activity", surface: "s", payload: { kind: "user", text: "second" } });
    state = applyMessage(state, { type: "prompt_summary", surface: "s", payload: { index: 1, text: "the second ask" } });

    const users = state.view.activity.filter((e) => e.kind === "user");
    expect(users[0].summary).toBeUndefined();
    expect(users[1].summary).toBe("the second ask");
  });
});
