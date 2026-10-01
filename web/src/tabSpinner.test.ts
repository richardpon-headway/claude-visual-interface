import { describe, expect, it } from "vitest";

import { ORBIT_CYCLE, ORBIT_FRAMES, tabSpinnerFrame } from "./tabSpinner";

// Count the lit dots in a braille glyph: codepoint minus the U+2800 base is an 8-bit dot
// mask, so the popcount of that offset is the number of raised dots.
function litDots(char: string): number {
  const offset = char.codePointAt(0)! - 0x2800;
  let count = 0;
  for (let bit = offset; bit > 0; bit >>= 1) count += bit & 1;
  return count;
}

describe("tabSpinnerFrame", () => {
  it("always renders exactly three braille-range characters", () => {
    for (let tick = 0; tick < ORBIT_CYCLE * 2; tick++) {
      const bars = [...tabSpinnerFrame(tick)];
      expect(bars).toHaveLength(3);
      for (const bar of bars) {
        const cp = bar.codePointAt(0)!;
        expect(cp).toBeGreaterThanOrEqual(0x2800);
        expect(cp).toBeLessThanOrEqual(0x28ff);
      }
    }
  });

  it("lights exactly one dot per frame — a single orbiting point", () => {
    for (const frame of ORBIT_FRAMES) {
      const total = [...frame].reduce((sum, char) => sum + litDots(char), 0);
      expect(total).toBe(1);
    }
  });

  it("has no duplicate frames — every orbit position is distinct", () => {
    expect(new Set(ORBIT_FRAMES).size).toBe(ORBIT_FRAMES.length);
  });

  it("repeats every ORBIT_CYCLE ticks", () => {
    for (let tick = 0; tick < ORBIT_CYCLE; tick++) {
      expect(tabSpinnerFrame(tick)).toBe(tabSpinnerFrame(tick + ORBIT_CYCLE));
    }
  });
});
