import { useCallback, useEffect, useRef, useState } from "react";

import { applyMessage, emptySurface, parseMessage } from "./viewState";
import type { Finding, SurfaceState } from "./viewState";

function surfaceUrl(surface: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/${encodeURIComponent(surface)}`;
}

// A pasted image: MIME type + raw base64 (no data-URL prefix), matching the SDK
// image block the daemon builds.
export type ImageAttachment = { media_type: string; data: string };
export type SendMessage = (text: string, image?: ImageAttachment) => void;
export type StopAgent = () => void;

/**
 * Subscribe to a surface. Returns its full state — the live view plus findings —
 * a `sendMessage` that pushes a chat turn to the surface's agent over the same
 * socket, and a `stop` that aborts whatever the agent is currently doing. On
 * (re)subscribe it fetches the current findings + status once over HTTP, then
 * stays current from WebSocket events. Re-subscribes when `surface` changes.
 */
export function useSurfaceSocket(surface: string): [SurfaceState, SendMessage, StopAgent] {
  const [state, setState] = useState<SurfaceState>(() => emptySurface(surface));
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    setState(emptySurface(surface));
    let cancelled = false;

    fetch(`/sessions/${encodeURIComponent(surface)}/findings`)
      .then((res) => (res.ok ? res.json() : { findings: [] }))
      .then((data: { findings?: Finding[] }) => {
        if (cancelled) return;
        const fetched = Object.fromEntries((data.findings ?? []).map((f) => [f.id, f]));
        setState((prev) => ({ ...prev, findings: { ...fetched, ...prev.findings } }));
      })
      .catch(() => {
        /* daemon unreachable or no findings yet — live events still flow */
      });

    fetch(`/sessions/${encodeURIComponent(surface)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: unknown) => {
        if (cancelled) return;
        // Trust boundary: only adopt a string status. A live `status` event wins
        // if the two race (prev.status set already), matching the findings merge.
        const status = typeof data === "object" && data !== null ? (data as { status?: unknown }).status : null;
        if (typeof status !== "string") return;
        setState((prev) => (prev.status === null ? { ...prev, status } : prev));
      })
      .catch(() => {
        /* daemon unreachable — the status chip stays unknown, live events still flow */
      });

    const ws = new WebSocket(surfaceUrl(surface));
    wsRef.current = ws;
    ws.onmessage = (event) => {
      const msg = parseMessage(event.data);
      if (msg) {
        setState((prev) => applyMessage(prev, msg));
      }
    };
    return () => {
      cancelled = true;
      wsRef.current = null;
      ws.close();
    };
  }, [surface]);

  const sendMessage = useCallback<SendMessage>((text, image) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "message", payload: { text, ...(image ? { image } : {}) } }));
    }
  }, []);

  const stop = useCallback<StopAgent>(() => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
  }, []);

  return [state, sendMessage, stop];
}
