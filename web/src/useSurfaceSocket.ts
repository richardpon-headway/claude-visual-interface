import { useCallback, useEffect, useRef, useState } from "react";

import { applyMessage, emptySurface, parseMessage } from "./viewState";
import type { SurfaceState } from "./viewState";

function surfaceUrl(surface: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/${encodeURIComponent(surface)}`;
}

// A pasted image: MIME type + raw base64 (no data-URL prefix), matching the SDK
// image block the daemon builds.
export type ImageAttachment = { media_type: string; data: string };
export type SendMessage = (text: string, images?: ImageAttachment[]) => void;
export type StopAgent = () => void;
// Submit an AskUserQuestion picker selection: the entry's ask id + the chosen value(s).
export type SendAnswer = (askId: string, answer: string) => void;
// Optimistically set the local starred flag (after POSTing star/unstar). No live
// event exists in v1, so the caller owns the local flip.
export type SetStarred = (next: boolean) => void;
// Socket connectivity, surfaced so the UI can show a reconnecting state.
export type Connection = "connecting" | "open" | "closed";

// Reconnect backoff after an unexpected close: start low, double, cap — so the tab
// recovers quickly after a daemon restart (Ctrl-C) without hammering while it's down.
const RECONNECT_MIN_MS = 500;
const RECONNECT_MAX_MS = 5000;

/**
 * Subscribe to a surface. Returns its full state, a `sendMessage`/`stop`/`sendAnswer`
 * trio that push over the socket, and the live `connection` state. The socket
 * auto-reconnects with backoff after an unexpected close (e.g. a daemon restart), and
 * outbound `message`/`answer` frames sent while disconnected are queued and flushed in
 * order on reconnect — so a message typed during the gap is never lost. `stop` is
 * best-effort (not queued): there's nothing to stop while disconnected, and run state
 * resyncs from the connect snapshot. Re-subscribes when `surface` changes.
 */
export function useSurfaceSocket(
  surface: string,
): [SurfaceState, SendMessage, StopAgent, SendAnswer, Connection, SetStarred] {
  const [state, setState] = useState<SurfaceState>(() => emptySurface(surface));
  const [connection, setConnection] = useState<Connection>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  // Outbound frames buffered while the socket is down; flushed in order on open.
  const pendingRef = useRef<string[]>([]);
  // Once the user toggles the star locally, don't let the async HTTP seed clobber it.
  const starredTouchedRef = useRef(false);

  useEffect(() => {
    setState(emptySurface(surface));
    setConnection("connecting");
    pendingRef.current = [];
    starredTouchedRef.current = false;
    let closedByCleanup = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let backoff = RECONNECT_MIN_MS;

    // Seed title/starred once over HTTP; live events (and the connect snapshot sent on
    // every reconnect) keep title current afterward. A live event wins if they race.
    // starred has no live event in v1 — the seed is the source of truth unless the user
    // has already toggled it locally.
    fetch(`/sessions/${encodeURIComponent(surface)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: unknown) => {
        if (closedByCleanup) return;
        const row =
          typeof data === "object" && data !== null
            ? (data as { title?: unknown; starred_at?: unknown })
            : {};
        setState((prev) => {
          let next = prev;
          if (typeof row.title === "string" && prev.title === null) next = { ...next, title: row.title };
          if (!starredTouchedRef.current) next = { ...next, starred: row.starred_at != null };
          return next;
        });
      })
      .catch(() => {
        /* daemon unreachable — live events still flow once the socket connects */
      });

    function connect() {
      setConnection("connecting");
      const ws = new WebSocket(surfaceUrl(surface));
      wsRef.current = ws;
      ws.onopen = () => {
        backoff = RECONNECT_MIN_MS;
        setConnection("open");
        // Flush anything typed while disconnected, in order.
        const pending = pendingRef.current;
        pendingRef.current = [];
        for (const frame of pending) ws.send(frame);
      };
      ws.onmessage = (event) => {
        const msg = parseMessage(event.data);
        if (msg) setState((prev) => applyMessage(prev, msg));
      };
      ws.onclose = () => {
        if (closedByCleanup) return; // unmount / surface change — don't reconnect
        setConnection("closed");
        // Retry until the daemon is back (e.g. after a Ctrl-C restart).
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
      };
      ws.onerror = () => {
        // An error is followed by close; close explicitly so onclose drives reconnect.
        ws.close();
      };
    }
    connect();

    return () => {
      closedByCleanup = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [surface]);

  // Send the frame now if the socket is open, else buffer it for flush on reconnect.
  const enqueueOrSend = useCallback((frame: string) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(frame);
    else pendingRef.current.push(frame);
  }, []);

  const sendMessage = useCallback<SendMessage>(
    (text, images) => {
      enqueueOrSend(
        JSON.stringify({
          type: "message",
          payload: { text, ...(images?.length ? { images } : {}) },
        }),
      );
    },
    [enqueueOrSend],
  );

  const sendAnswer = useCallback<SendAnswer>(
    (askId, answer) => {
      enqueueOrSend(JSON.stringify({ type: "answer", payload: { id: askId, answer } }));
    },
    [enqueueOrSend],
  );

  const stop = useCallback<StopAgent>(() => {
    // Best-effort, not queued: a stop only makes sense against a live, open socket.
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
  }, []);

  const setStarred = useCallback<SetStarred>((next) => {
    starredTouchedRef.current = true;
    setState((prev) => ({ ...prev, starred: next }));
  }, []);

  return [state, sendMessage, stop, sendAnswer, connection, setStarred];
}
