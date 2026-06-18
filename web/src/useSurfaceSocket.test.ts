import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSurfaceSocket } from "./useSurfaceSocket";

// A stateful stand-in for the browser WebSocket: starts CONNECTING, opens/closes on
// demand, records sends, and fires the lifecycle handlers the hook registers.
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
  // Test helpers:
  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
  drop() {
    // Simulate the server going away (e.g. a Ctrl-C daemon restart).
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }
  static get last(): FakeWebSocket | null {
    return FakeWebSocket.instances.at(-1) ?? null;
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  // The hook fetches status/title on connect; keep that quiet.
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("no network in test"))));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const MSG = (text: string) => JSON.stringify({ type: "message", payload: { text } });

describe("useSurfaceSocket", () => {
  it("sendMessage posts a message frame over an open socket", () => {
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    act(() => FakeWebSocket.last!.open());
    act(() => result.current[1]("review the diff"));

    expect(FakeWebSocket.last?.sent).toEqual([MSG("review the diff")]);
  });

  it("includes the images array in the frame when attached, and omits it otherwise", () => {
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    act(() => FakeWebSocket.last!.open());
    act(() =>
      result.current[1]("look", [
        { media_type: "image/png", data: "QUJD" },
        { media_type: "image/png", data: "WFla" },
      ]),
    );
    // No images → the key is omitted entirely.
    act(() => result.current[1]("text only"));
    act(() => result.current[1]("empty list", []));

    expect(FakeWebSocket.last?.sent).toEqual([
      JSON.stringify({
        type: "message",
        payload: {
          text: "look",
          images: [
            { media_type: "image/png", data: "QUJD" },
            { media_type: "image/png", data: "WFla" },
          ],
        },
      }),
      MSG("text only"),
      MSG("empty list"),
    ]);
  });

  it("stop sends a stop frame over an open socket", () => {
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    act(() => FakeWebSocket.last!.open());
    act(() => result.current[2]());

    expect(FakeWebSocket.last?.sent).toEqual([JSON.stringify({ type: "stop" })]);
  });

  it("queues a message sent while not open and flushes it in order on open", () => {
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    const ws = FakeWebSocket.last!;
    // Still CONNECTING — sends are buffered, not dropped.
    act(() => result.current[1]("first"));
    act(() => result.current[3]("ask-1", "Custom modal")); // sendAnswer also queues
    expect(ws.sent).toEqual([]);

    act(() => ws.open());
    expect(ws.sent).toEqual([
      MSG("first"),
      JSON.stringify({ type: "answer", payload: { id: "ask-1", answer: "Custom modal" } }),
    ]);
  });

  it("reconnects after an unexpected close and flushes what was queued while down", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    const first = FakeWebSocket.last!;
    act(() => first.open());

    // Server drops (Ctrl-C). A message typed while down is queued, not lost.
    act(() => first.drop());
    act(() => result.current[1]("after drop"));
    expect(first.sent).toEqual([]);

    // Backoff elapses → a fresh socket is created and the queue flushes on open.
    act(() => vi.advanceTimersByTime(600));
    const second = FakeWebSocket.last!;
    expect(second).not.toBe(first);
    act(() => second.open());
    expect(second.sent).toEqual([MSG("after drop")]);
  });

  it("exposes connection state transitions", () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useSurfaceSocket("s1"));
    expect(result.current[4]).toBe("connecting");
    act(() => FakeWebSocket.last!.open());
    expect(result.current[4]).toBe("open");
    act(() => FakeWebSocket.last!.drop());
    expect(result.current[4]).toBe("closed");
    act(() => vi.advanceTimersByTime(600));
    expect(result.current[4]).toBe("connecting");
    act(() => FakeWebSocket.last!.open());
    expect(result.current[4]).toBe("open");
  });

  it("does not reconnect when the hook unmounts", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useSurfaceSocket("s1"));
    act(() => FakeWebSocket.last!.open());
    const count = FakeWebSocket.instances.length;

    unmount(); // cleanup closes the socket; this must NOT schedule a reconnect
    act(() => vi.advanceTimersByTime(5000));
    expect(FakeWebSocket.instances.length).toBe(count);
  });
});
