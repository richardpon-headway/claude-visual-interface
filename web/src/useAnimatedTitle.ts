import { useEffect, useState } from "react";

import { SPINNER_TICK_MS } from "./braille";
import { composeTitle } from "./title";
import { EQ_CYCLE, tabEqualizerFrame } from "./tabEqualizer";

// Drive the browser-tab title: while the session is working, prefix a cycling three-bar
// block-glyph equalizer; otherwise defer to composeTitle (turn-end waves, or the plain
// base). Owns the single document.title write and the spinner interval, and restores the
// default on unmount. The interval only runs while working, mirroring ThinkingIndicator.
export function useAnimatedTitle(base: string, working: boolean, wavesUnseen: boolean): void {
  const [frameIndex, setFrameIndex] = useState(0);

  // Advance the equalizer only while working; no timer runs when idle.
  useEffect(() => {
    if (!working) return;
    setFrameIndex(0);
    const id = setInterval(() => setFrameIndex((i) => (i + 1) % EQ_CYCLE), SPINNER_TICK_MS);
    return () => clearInterval(id);
  }, [working]);

  // Write the composed title on every input or frame change.
  useEffect(() => {
    const frame = working ? tabEqualizerFrame(frameIndex) : null;
    document.title = composeTitle(base, frame, wavesUnseen);
  }, [base, working, wavesUnseen, frameIndex]);

  // Restore the default title only when no surface is mounted.
  useEffect(() => {
    return () => {
      document.title = "Claude Visual Interface";
    };
  }, []);
}
