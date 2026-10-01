import { describe, expect, it } from "vitest";

import { TWINKLE_CYCLE, tabSpinnerFrame } from "./tabSpinner";

// Count the lit dots in a braille glyph: codepoint minus the U+2800 base is an 8-bit dot
// mask, so the popcount of that offset is the number of raised dots.
function litDots(char: string): number {
  const offset = char.codePointAt(0)! - 0x2800;
  let count = 0;
  for (let bit = offset; bit > 0; bit >>= 1) count += bit & 1;
  return count;
}

function totalLit(tick: number): number {
  return [...tabSpinnerFrame(tick)].reduce((sum, char) => sum + litDots(char), 0);
}

describe("tabSpinnerFrame", () => {
  it("always renders exactly three braille-range characters", () => {
    for (let tick = 0; tick < TWINKLE_CYCLE; tick++) {
      const bars = [...tabSpinnerFrame(tick)];
      expect(bars).toHaveLength(3);
      for (const bar of bars) {
        const cp = bar.codePointAt(0)!;
        expect(cp).toBeGreaterThanOrEqual(0x2800);
        expect(cp).toBeLessThanOrEqual(0x28ff);
      }
    }
  });

  it("is deterministic — a tick always yields the same frame", () => {
    for (const tick of [0, 7, 42, 500, 996]) {
      expect(tabSpinnerFrame(tick)).toBe(tabSpinnerFrame(tick));
    }
  });

  it("repeats every TWINKLE_CYCLE ticks", () => {
    for (let tick = 0; tick < TWINKLE_CYCLE; tick++) {
      expect(tabSpinnerFrame(tick)).toBe(tabSpinnerFrame(tick + TWINKLE_CYCLE));
    }
  });

  it("lights at least one dot every frame — never a blank prefix", () => {
    for (let tick = 0; tick < TWINKLE_CYCLE; tick++) {
      expect(totalLit(tick)).toBeGreaterThanOrEqual(1);
    }
  });

  it("stays sparse — mostly dark, only a few dots lit", () => {
    let sum = 0;
    let max = 0;
    for (let tick = 0; tick < TWINKLE_CYCLE; tick++) {
      const count = totalLit(tick);
      sum += count;
      max = Math.max(max, count);
    }
    const mean = sum / TWINKLE_CYCLE;
    expect(mean).toBeGreaterThan(1);
    expect(mean).toBeLessThan(6);
    expect(max).toBeLessThanOrEqual(12);
  });
});
