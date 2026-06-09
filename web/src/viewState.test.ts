import { describe, expect, it } from "vitest";

import { applyMessage, emptySurface, emptyViewState, parseMessage } from "./viewState";
import type { Finding, ViewState } from "./viewState";

function finding(id: string, overrides: Partial<Finding> = {}): Finding {
  return {
    id,
    session_id: "s",
    file: "a.py",
    anchor: null,
    severity: "high",
    title: "t",
    body: "b",
    suggested_patch: null,
    source_lens: null,
    actions: null,
    disposition: null,
    ...overrides,
  };
}

describe("parseMessage", () => {
  it("parses known message types incl. finding/disposition", () => {
    expect(parseMessage(JSON.stringify({ type: "finding", surface: "s", payload: {} }))?.type).toBe("finding");
    expect(parseMessage(JSON.stringify({ type: "disposition", surface: "s", payload: {} }))?.type).toBe(
      "disposition",
    );
  });

  it("rejects malformed JSON and unknown types", () => {
    expect(parseMessage("{nope")).toBeNull();
    expect(parseMessage(JSON.stringify({ type: "explode" }))).toBeNull();
  });
});

describe("applyMessage — view events", () => {
  it("replaces the view on a snapshot but keeps findings", () => {
    const incoming: ViewState = {
      surface: "s",
      panes: 2,
      open: {},
      highlights: {},
      diff: null,
      selection: null,
      activity: [],
    };
    let state = emptySurface("s");
    state = applyMessage(state, { type: "finding", surface: "s", payload: finding("f1") });
    state = applyMessage(state, { type: "snapshot", surface: "s", payload: incoming });
    expect(state.view.panes).toBe(2);
    expect(state.findings["f1"]).toBeDefined(); // snapshot is view-only; findings survive
  });

  it("records an opened file at its pane", () => {
    const next = applyMessage(emptySurface("s"), {
      type: "open_code",
      surface: "s",
      payload: { file: "a.py", range: { start: 1, end: 4 }, pane: 1 },
    });
    expect(next.view.open["1"]).toEqual({ file: "a.py", range: { start: 1, end: 4 } });
  });

  it("trims orphaned panes when a split shrinks", () => {
    let state = emptySurface("s");
    state = applyMessage(state, { type: "open_code", surface: "s", payload: { file: "a", range: null, pane: 0 } });
    state = applyMessage(state, { type: "open_code", surface: "s", payload: { file: "b", range: null, pane: 1 } });
    state = applyMessage(state, { type: "split_pane", surface: "s", payload: { n: 1 } });
    expect(Object.keys(state.view.open)).toEqual(["0"]);
  });

  it("emptyViewState starts blank", () => {
    expect(emptyViewState("s")).toEqual({
      surface: "s",
      panes: 1,
      open: {},
      highlights: {},
      diff: null,
      selection: null,
      activity: [],
    });
  });
});

describe("applyMessage — activity & status", () => {
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

  it("seeds activity from a snapshot but leaves status untouched", () => {
    const incoming: ViewState = {
      surface: "s",
      panes: 1,
      open: {},
      highlights: {},
      diff: null,
      selection: null,
      activity: [{ kind: "text", text: "buffered" }],
    };
    let state = applyMessage(emptySurface("s"), { type: "status", surface: "s", payload: { status: "running" } });
    state = applyMessage(state, { type: "snapshot", surface: "s", payload: incoming });
    expect(state.view.activity).toEqual([{ kind: "text", text: "buffered" }]);
    expect(state.status).toBe("running"); // snapshot is view-only; status survives
  });
});

describe("applyMessage — finding events", () => {
  it("adds and updates a finding by id", () => {
    let state = emptySurface("s");
    state = applyMessage(state, { type: "finding", surface: "s", payload: finding("f1", { title: "first" }) });
    state = applyMessage(state, { type: "finding", surface: "s", payload: finding("f1", { title: "updated" }) });
    expect(Object.keys(state.findings)).toEqual(["f1"]);
    expect(state.findings["f1"].title).toBe("updated");
  });

  it("applies a disposition to an existing finding", () => {
    let state = emptySurface("s");
    state = applyMessage(state, { type: "finding", surface: "s", payload: finding("f1") });
    state = applyMessage(state, { type: "disposition", surface: "s", payload: { finding_id: "f1", value: "dismissed" } });
    expect(state.findings["f1"].disposition).toBe("dismissed");
  });

  it("ignores a disposition for an unknown finding", () => {
    const state = applyMessage(emptySurface("s"), {
      type: "disposition",
      surface: "s",
      payload: { finding_id: "ghost", value: "fixed" },
    });
    expect(state.findings).toEqual({});
  });
});
