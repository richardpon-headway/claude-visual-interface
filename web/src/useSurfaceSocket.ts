import { useEffect, useState } from "react";

import { applyMessage, emptyViewState, parseMessage } from "./viewState";
import type { ViewState } from "./viewState";

function surfaceUrl(surface: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/${encodeURIComponent(surface)}`;
}

/**
 * Subscribe to a surface's live stream. Returns the current view state, which
 * starts empty, is replaced by the snapshot on connect, then advances as
 * view-control events arrive. Re-subscribes when `surface` changes.
 */
export function useSurfaceSocket(surface: string): ViewState {
  const [state, setState] = useState<ViewState>(() => emptyViewState(surface));

  useEffect(() => {
    setState(emptyViewState(surface));
    const ws = new WebSocket(surfaceUrl(surface));
    ws.onmessage = (event) => {
      const msg = parseMessage(event.data);
      if (msg) {
        setState((prev) => applyMessage(prev, msg));
      }
    };
    return () => ws.close();
  }, [surface]);

  return state;
}
