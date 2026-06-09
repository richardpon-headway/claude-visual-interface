import { describe, expect, it } from "vitest";

import { toDecorations } from "./decorations";
import type { Finding } from "./viewState";

function finding(overrides: Partial<Finding>): Finding {
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

describe("toDecorations", () => {
  it("decorates an anchored finding in the open file", () => {
    const decs = toDecorations("a.py", [finding({})], {});
    expect(decs).toEqual([{ startLine: 3, endLine: 5, kind: "finding", severity: "high" }]);
  });

  it("ignores findings for other files", () => {
    expect(toDecorations("a.py", [finding({ file: "other.py" })], {})).toEqual([]);
  });

  it("ignores findings without an anchor", () => {
    expect(toDecorations("a.py", [finding({ anchor: null })], {})).toEqual([]);
  });

  it("includes view highlights for the file and skips other files'", () => {
    const decs = toDecorations("a.py", [], {
      "a.py": [{ start: 1, end: 2 }],
      "other.py": [{ start: 9, end: 9 }],
    });
    expect(decs).toEqual([{ startLine: 1, endLine: 2, kind: "highlight", severity: null }]);
  });
});
