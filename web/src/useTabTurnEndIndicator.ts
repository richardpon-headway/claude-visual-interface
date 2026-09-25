import { useEffect, useRef, useState } from "react";

// Track whether a turn ended without the tab being looked at since, so the caller can
// reflect it in the browser-tab title. "Turn ended" is the falling edge of `thinking`
// (true -> false); "looked at" is the tab becoming visible or the window regaining
// focus. It flags on every turn-end regardless of focus, so a turn that finishes while
// you're watching stays flagged until the tab next loses and regains focus.
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

  // Reset when switching sessions so a stale flag never carries into another surface.
  useEffect(() => {
    setUnseen(false);
  }, [surface]);

  return unseen;
}
