import { useEffect, useRef, useState } from "react";

import { setTurnEndFavicon } from "./favicon";

// Track whether a turn ended without the tab being looked at since. On turn-end it
// puts a dot on the tab favicon and returns the flag so the caller can also reflect it
// in the title; both clear when the tab is looked at again. "Turn ended" is the falling
// edge of `thinking` (true -> false); "looked at" is the tab becoming visible or the
// window regaining focus. It flags on every turn-end regardless of focus, so a turn
// that finishes while you're watching stays flagged until the tab next loses and
// regains focus.
export function useTabTurnEndIndicator(surface: string, thinking: boolean): boolean {
  const [unseen, setUnseen] = useState(false);
  // Seeded with the first observed value so joining mid-turn (the connect snapshot
  // can arrive with `thinking` already true) is not mistaken for a fresh edge.
  const prevThinking = useRef(thinking);

  useEffect(() => {
    const prev = prevThinking.current;
    prevThinking.current = thinking;
    if (prev && !thinking) {
      setUnseen(true); // turn just ended
    } else if (!prev && thinking) {
      setUnseen(false); // a new turn started — drop any stale flag
    }
  }, [thinking]);

  useEffect(() => {
    function clearIfVisible() {
      if (document.visibilityState === "visible") setUnseen(false);
    }
    function clear() {
      setUnseen(false);
    }
    document.addEventListener("visibilitychange", clearIfVisible);
    window.addEventListener("focus", clear);
    return () => {
      document.removeEventListener("visibilitychange", clearIfVisible);
      window.removeEventListener("focus", clear);
    };
  }, []);

  useEffect(() => {
    setTurnEndFavicon(unseen);
  }, [unseen]);

  // Reset when switching sessions (and revert the favicon on unmount) so a stale flag
  // never carries into another surface.
  useEffect(() => {
    setUnseen(false);
    return () => {
      setTurnEndFavicon(false);
    };
  }, [surface]);

  return unseen;
}
