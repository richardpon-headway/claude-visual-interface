import { describe, expect, it } from "vitest";

import { primaryOpenFile } from "./findingFocus";
import type { Finding, OpenFile } from "./viewState";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f",
    session_id: "s",
    file: "a.py",
    anchor: { snippet: "x", range: { start: 3, end: 5 } },
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

describe("primaryOpenFile", () => {
  it("opens the active finding's file at its anchor range", () => {
    expect(primaryOpenFile(finding(), undefined)).toEqual({
      file: "a.py",
      range: { start: 3, end: 5 },
    });
  });

  it("opens an anchor-less finding's file with no range", () => {
    expect(primaryOpenFile(finding({ anchor: null }), undefined)).toEqual({
      file: "a.py",
      range: null,
    });
  });

  it("wins over the daemon-pushed open file", () => {
    const open: OpenFile = { file: "other.py", range: null };
    expect(primaryOpenFile(finding({ file: "a.py", anchor: null }), open)?.file).toBe("a.py");
  });

  it("falls back to the daemon open file when no finding is active", () => {
    const open: OpenFile = { file: "other.py", range: { start: 1, end: 2 } };
    expect(primaryOpenFile(null, open)).toBe(open);
  });

  it("returns undefined when nothing is open", () => {
    expect(primaryOpenFile(null, undefined)).toBeUndefined();
  });
});
