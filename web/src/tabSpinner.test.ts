import { describe, expect, it } from "vitest";

import { SPINNER_CYCLE, tabSpinnerFrame } from "./tabSpinner";

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

// The set of lit "row,globalCol" positions across the three cells for a given tick,
// derived back from the rendered glyphs so the test exercises the real output.
function litPositions(tick: number): Set<string> {
  const BIT_TO_ROW_COL: Record<number, [number, number]> = {
    0: [0, 0],
    1: [1, 0],
    2: [2, 0],
    6: [3, 0],
    3: [0, 1],
    4: [1, 1],
    5: [2, 1],
    7: [3, 1],
  };
  const positions = new Set<string>();
  [...tabSpinnerFrame(tick)].forEach((char, cell) => {
    const offset = char.codePointAt(0)! - 0x2800;
    for (let bit = 0; bit < 8; bit++) {
      if (offset & (1 << bit)) {
        const [row, col] = BIT_TO_ROW_COL[bit];
        positions.add(`${row},${cell * 2 + col}`);
      }
    }
  });
  return positions;
}

// The comet head at tick t: the one position lit at t but not at t-1 (the tail trails).
function head(tick: number): string {
  const prev = litPositions(tick - 1);
  return [...litPositions(tick)].filter((p) => !prev.has(p))[0];
}

describe("tabSpinnerFrame", () => {
  it("always renders exactly three braille-range characters", () => {
    for (let tick = 0; tick < SPINNER_CYCLE; tick++) {
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
    for (const tick of [0, 3, 7, 15, 128]) {
      expect(tabSpinnerFrame(tick)).toBe(tabSpinnerFrame(tick));
    }
  });

  it("repeats every SPINNER_CYCLE ticks", () => {
    for (let tick = 0; tick < SPINNER_CYCLE; tick++) {
      expect(tabSpinnerFrame(tick)).toBe(tabSpinnerFrame(tick + SPINNER_CYCLE));
    }
  });

  it("lights exactly three dots every frame — the comet head plus a two-dot tail", () => {
    for (let tick = 0; tick < SPINNER_CYCLE; tick++) {
      expect(totalLit(tick)).toBe(3);
    }
  });

  it("one full orbit visits every path position exactly once as the head", () => {
    const heads = new Set<string>();
    for (let tick = 0; tick < SPINNER_CYCLE; tick++) heads.add(head(tick));
    expect(heads.size).toBe(SPINNER_CYCLE);
  });

  it("moves continuously — each tick the head steps to an orthogonally adjacent position", () => {
    for (let tick = 0; tick < SPINNER_CYCLE; tick++) {
      const [pr, pc] = head(tick).split(",").map(Number);
      const [nr, nc] = head(tick + 1).split(",").map(Number);
      expect(Math.abs(pr - nr) + Math.abs(pc - nc)).toBe(1);
    }
  });
});
