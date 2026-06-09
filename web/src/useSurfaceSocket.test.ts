import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSurfaceSocket } from "./useSurfaceSocket";

// A minimal stand-in for the browser WebSocket: records sends, reports OPEN.
class FakeWebSocket {
  static OPEN = 1;
  static last: FakeWebSocket | null = null;
  readyState = FakeWebSocket.OPEN;
  sent: string[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.last = this;
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {}
}

beforeEach(() => {
  FakeWebSocket.last = null;
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  // The hook fetches findings + status on connect; keep those quiet.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("no network in test"))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useSurfaceSocket", () => {
  it("sendMessage posts a message frame over the socket", () => {
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    act(() => result.current[1]("review the diff"));

    expect(FakeWebSocket.last?.sent).toEqual([
      JSON.stringify({ type: "message", payload: { text: "review the diff" } }),
    ]);
  });
});
