import { useEffect, useRef, useState } from "react";

import { setFaviconBadge } from "./favicon";

// Badge the browser-tab favicon when a turn ends, and clear it once the tab is
// looked at again. "Turn ended" is the falling edge of `thinking` (true -> false);
// "looked at" is the tab becoming visible or the window regaining focus. The badge
// fires on every turn-end regardless of focus, so a turn that finishes while you're
// watching still badges until the tab next loses and regains focus.
export function useTabTurnEndIndicator(surface: string, thinking: boolean): void {
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
      setUnseen(false); // a new turn started — drop any stale badge
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
    setFaviconBadge(unseen);
  }, [unseen]);

  // Clear the badge when leaving this surface (or unmounting) so navigation never
  // strands it on the tab.
  useEffect(() => {
    return () => {
      setFaviconBadge(false);
    };
  }, [surface]);
}
