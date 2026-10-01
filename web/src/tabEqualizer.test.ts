import { describe, expect, it } from "vitest";

import { EQ_CYCLE, EQ_LEVELS, tabEqualizerFrame } from "./tabEqualizer";

describe("tabEqualizerFrame", () => {
  it("always renders exactly three block glyphs from EQ_LEVELS", () => {
    for (let tick = 0; tick < EQ_CYCLE * 2; tick++) {
      const frame = tabEqualizerFrame(tick);
      const bars = [...frame];
      expect(bars).toHaveLength(3);
      for (const bar of bars) expect(EQ_LEVELS).toContain(bar);
    }
  });

  it("is never fully synchronized — the three bars are never all equal", () => {
    for (let tick = 0; tick < EQ_CYCLE; tick++) {
      const [a, b, c] = [...tabEqualizerFrame(tick)];
      expect(a === b && b === c).toBe(false);
    }
  });

  it("actually animates — more than one distinct frame across a cycle", () => {
    const frames = new Set<string>();
    for (let tick = 0; tick < EQ_CYCLE; tick++) frames.add(tabEqualizerFrame(tick));
    expect(frames.size).toBeGreaterThan(1);
  });

  it("repeats every EQ_CYCLE ticks", () => {
    for (let tick = 0; tick < EQ_CYCLE; tick++) {
      expect(tabEqualizerFrame(tick)).toBe(tabEqualizerFrame(tick + EQ_CYCLE));
    }
  });
});
