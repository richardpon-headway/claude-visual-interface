// The browser-tab busy indicator, drawn across three braille cells. Three cells form a
// 6-wide × 4-tall field of 24 dots; each tick a few dots light at random while the rest
// stay dark, so the title reads as a soft random twinkle rather than a moving shape.
//
// A braille glyph is a single solid color, so dots can only be on/off — a text title has
// no per-dot brightness, so the "pulse" is the random on/off churn, not a fade.
//
// A tab title is plain text — no real animated graphics — and a background tab throttles
// the frame timer to ~1 update/sec; a sparse twinkle degrades gracefully there (it just
// twinkles slower) and never shows a blank prefix, because at least one dot is always lit.
//
// The in-app ThinkingIndicator keeps its own braille spinner (see braille.ts); only the
// tab title uses this, so the two are intentionally separate.

// Ticks before the twinkle pattern repeats; useAnimatedTitle advances modulo this to keep
// the counter bounded. A prime keeps the loop long enough (~2 min at SPINNER_TICK_MS) that
// the repeat is imperceptible.
export const TWINKLE_CYCLE = 997;

// Probability each of the 24 dots is lit on a given tick: ~0.14 × 24 ≈ 3 dots on average —
// "mostly dark, a few pulsing." Tune alongside SPINNER_TICK_MS (cadence) to taste.
const DOT_PROB = 0.14;
const DOTS_PER_CELL = 8; // a braille cell is an 8-dot (2×4) grid
const TOTAL_DOTS = 3 * DOTS_PER_CELL;

// Deterministic pseudo-random in [0, 1) from an integer — a cheap integer hash (no global
// RNG, no Math.random), so a given tick always yields the same frame and tests are stable.
function hash01(n: number): number {
  let x = (n + 0x9e3779b9) | 0;
  x = Math.imul(x ^ (x >>> 16), 0x21f0aaad);
  x = Math.imul(x ^ (x >>> 15), 0x735a2d97);
  x = x ^ (x >>> 15);
  return (x >>> 0) / 4294967296;
}

// The 3-character twinkle frame for a given tick.
export function tabSpinnerFrame(tick: number): string {
  const t = ((tick % TWINKLE_CYCLE) + TWINKLE_CYCLE) % TWINKLE_CYCLE;
  const masks = [0, 0, 0];
  let lit = 0;
  for (let d = 0; d < TOTAL_DOTS; d++) {
    if (hash01(t * TOTAL_DOTS + d) < DOT_PROB) {
      masks[(d / DOTS_PER_CELL) | 0] |= 1 << (d % DOTS_PER_CELL);
      lit++;
    }
  }
  // Never emit three blank cells (a throttled background tab would show an empty prefix for
  // a full second): light one deterministic dot when a tick happens to roll all-dark.
  if (lit === 0) {
    masks[((t / DOTS_PER_CELL) | 0) % 3] |= 1 << (t % DOTS_PER_CELL);
  }
  return masks.map((m) => String.fromCodePoint(0x2800 + m)).join("");
}
