// The browser-tab busy indicator: a single bright dot with a short trailing tail that
// orbits the three braille cells, so the title reads as one deliberate point in motion
// rather than a cluster or a random shimmer.
//
// A braille glyph draws only its lit dots — an unset position is blank and U+2800 is
// empty (verified against macOS's "Apple Braille" fallback: a one-dot codepoint renders
// exactly one dot, nothing fills the gaps). So a sparse pattern renders as a few crisp
// dots on an empty background — exactly what a moving comet needs.
//
// The three cells form a 6-wide × 4-tall field of 24 dot positions; the comet walks a
// fixed loop around the perimeter of that field, one step per tick. A tab title is plain
// text with no per-dot brightness, so the "tail" is a short solid streak (the positions
// just behind the head), not a brightness fade. A background tab throttles the frame
// timer to ~1 update/sec; the comet simply advances more slowly there, and because it
// always lights three dots it never shows a blank prefix.
//
// The in-app ThinkingIndicator keeps its own rotating single-cell braille spinner (see
// braille.ts); only the tab title uses this, so the two are intentionally separate.

// Braille dot bit for a (row, col) within a cell. Column 0/1 is the cell's left/right;
// rows 0–3 run top to bottom. Dot numbering 1–8 maps to bits 0–7 (bit = dot − 1):
//   col0 → dots 1,2,3,7  (bits 0,1,2,6)
//   col1 → dots 4,5,6,8  (bits 3,4,5,7)
const BIT_FOR_ROW_COL: number[][] = [
  [0, 3], // row 0
  [1, 4], // row 1
  [2, 5], // row 2
  [6, 7], // row 3
];

// A clockwise loop of [row, globalCol] positions around the perimeter of the 6×4 field.
// Consecutive entries are adjacent and the last wraps back to the first, so the comet
// moves continuously with no jump. 16 positions × SPINNER_TICK_MS ≈ one orbit every ~1.9s.
const PATH: Array<[number, number]> = [
  [0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], // top edge, L→R
  [1, 5], [2, 5], [3, 5], //                         right edge, top→bottom
  [3, 4], [3, 3], [3, 2], [3, 1], [3, 0], //         bottom edge, R→L
  [2, 0], [1, 0], //                                 left edge, bottom→top
];

// Ticks before the animation repeats — exactly one orbit, so useAnimatedTitle can advance
// modulo this and stay bounded without ever introducing a seam mid-loop.
export const SPINNER_CYCLE = PATH.length;

// Trailing positions lit behind the head (a short solid streak that gives the motion a
// clear direction). 2 → a 3-dot comet.
const TAIL = 2;

// The 3-character comet frame for a given tick.
export function tabSpinnerFrame(tick: number): string {
  const head = ((tick % SPINNER_CYCLE) + SPINNER_CYCLE) % SPINNER_CYCLE;
  const masks = [0, 0, 0];
  for (let i = 0; i <= TAIL; i++) {
    const [row, gcol] = PATH[(head - i + SPINNER_CYCLE) % SPINNER_CYCLE];
    masks[gcol >> 1] |= 1 << BIT_FOR_ROW_COL[row][gcol & 1];
  }
  return masks.map((m) => String.fromCodePoint(0x2800 + m)).join("");
}
