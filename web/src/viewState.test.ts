import { describe, expect, it } from "vitest";

import { applyMessage, emptyViewState, parseMessage } from "./viewState";
import type { ViewState } from "./viewState";

describe("parseMessage", () => {
  it("parses a known message type", () => {
    const msg = parseMessage(JSON.stringify({ type: "split_pane", surface: "s", payload: { n: 2 } }));
    expect(msg?.type).toBe("split_pane");
  });

  it("rejects malformed JSON", () => {
    expect(parseMessage("{not json")).toBeNull();
  });

  it("rejects an unknown message type", () => {
    expect(parseMessage(JSON.stringify({ type: "explode", payload: {} }))).toBeNull();
  });
});

describe("applyMessage", () => {
  it("replaces state wholesale on a snapshot", () => {
    const incoming: ViewState = {
      surface: "s",
      panes: 2,
      open: { "0": { file: "a.py", range: null } },
      highlights: {},
      diff: null,
    };
    const next = applyMessage(emptyViewState("s"), { type: "snapshot", surface: "s", payload: incoming });
    expect(next).toEqual(incoming);
  });

  it("records an opened file at its pane", () => {
    const next = applyMessage(emptyViewState("s"), {
      type: "open_code",
      surface: "s",
      payload: { file: "a.py", range: { start: 1, end: 4 }, pane: 1 },
    });
    expect(next.open["1"]).toEqual({ file: "a.py", range: { start: 1, end: 4 } });
  });

  it("trims orphaned panes when a split shrinks", () => {
    let state = emptyViewState("s");
    state = applyMessage(state, { type: "open_code", surface: "s", payload: { file: "a.py", range: null, pane: 0 } });
    state = applyMessage(state, { type: "open_code", surface: "s", payload: { file: "b.py", range: null, pane: 1 } });
    state = applyMessage(state, { type: "split_pane", surface: "s", payload: { n: 1 } });
    expect(state.panes).toBe(1);
    expect(Object.keys(state.open)).toEqual(["0"]);
  });

  it("accumulates highlights per file", () => {
    let state = emptyViewState("s");
    state = applyMessage(state, { type: "highlight_range", surface: "s", payload: { file: "a.py", range: { start: 1, end: 2 } } });
    state = applyMessage(state, { type: "highlight_range", surface: "s", payload: { file: "a.py", range: { start: 5, end: 6 } } });
    expect(state.highlights["a.py"]).toEqual([
      { start: 1, end: 2 },
      { start: 5, end: 6 },
    ]);
  });

  it("sets the current diff", () => {
    const next = applyMessage(emptyViewState("s"), {
      type: "show_diff",
      surface: "s",
      payload: { a: "current", b: "patch-1" },
    });
    expect(next.diff).toEqual({ a: "current", b: "patch-1" });
  });
});
