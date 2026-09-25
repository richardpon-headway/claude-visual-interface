import { useEffect, useRef, useState } from "react";

import { setTurnEndFavicon } from "./favicon";

// Swap the browser-tab favicon to a waving hand when a turn ends, and revert it once
// the tab is looked at again. "Turn ended" is the falling edge of `thinking`
// (true -> false); "looked at" is the tab becoming visible or the window regaining
// focus. It fires on every turn-end regardless of focus, so a turn that finishes
// while you're watching keeps waving until the tab next loses and regains focus.
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
      setUnseen(false); // a new turn started — drop any stale indicator
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

  // Revert the icon when leaving this surface (or unmounting) so navigation never
  // strands a waving hand on the tab.
  useEffect(() => {
    return () => {
      setTurnEndFavicon(false);
    };
  }, [surface]);
}
