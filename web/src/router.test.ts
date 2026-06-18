import { describe, expect, it } from "vitest";

import { routeFromPath } from "./router";
import { filterSessions } from "./session";
import type { Session } from "./session";

describe("routeFromPath", () => {
  it("routes the root to the launch landing (home)", () => {
    expect(routeFromPath("/")).toEqual({ kind: "home" });
  });

  it("routes /sessions to the session list", () => {
    expect(routeFromPath("/sessions")).toEqual({ kind: "sessions" });
  });

  it("routes /s/<id> to that surface, decoding the id", () => {
    expect(routeFromPath("/s/abc-123")).toEqual({ kind: "surface", surface: "abc-123" });
    expect(routeFromPath("/s/a%2Fb")).toEqual({ kind: "surface", surface: "a/b" });
  });

  it("falls back to home for unknown paths", () => {
    expect(routeFromPath("/whatever")).toEqual({ kind: "home" });
  });
});

describe("filterSessions", () => {
  const sessions = [
    { id: "1", title: "Fix the parser", status: "ready" },
    { id: "2", title: null, status: "running" },
  ] as Session[];

  it("returns all when the query is blank", () => {
    expect(filterSessions(sessions, "  ")).toHaveLength(2);
  });

  it("matches on title, case-insensitively", () => {
    expect(filterSessions(sessions, "PARSER").map((s) => s.id)).toEqual(["1"]);
  });

  it("falls back to matching the id when title is null", () => {
    expect(filterSessions(sessions, "2").map((s) => s.id)).toEqual(["2"]);
  });
});
