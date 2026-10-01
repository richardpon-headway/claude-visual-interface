// A single spinner for the browser-tab busy indicator, drawn across three braille cells.
// Each braille char is a 2×4 dot grid, so three in a row form one 6-wide × 4-tall dot
// canvas; a lone dot travels clockwise around its outer ring, reading as one large
// rotating spinner rather than three separate glyphs.
//
// A tab title is plain text — it can't render real animated bars — and a background tab
// throttles the frame timer to ~1 update/sec, so a rotation (which still reads as "slow
// spin" when stepped coarsely) degrades far better there than bouncing bars would.
//
// The in-app ThinkingIndicator keeps its own braille spinner (see braille.ts); only the
// tab title uses this, so the two are intentionally separate and do not share frames.

// The 16 perimeter positions of the 6×4 canvas, clockwise from the top-left dot. Every
// frame lights exactly one dot; two of the three cells are the braille blank (U+2800).
// Verified exhaustively (single dot, all distinct, braille range) in tabSpinner.test.ts.
export const ORBIT_FRAMES = [
  "⠁⠀⠀", // top edge, left → right …
  "⠈⠀⠀",
  "⠀⠁⠀",
  "⠀⠈⠀",
  "⠀⠀⠁",
  "⠀⠀⠈",
  "⠀⠀⠐", // right edge, top → bottom …
  "⠀⠀⠠",
  "⠀⠀⢀",
  "⠀⠀⡀", // bottom edge, right → left …
  "⠀⢀⠀",
  "⠀⡀⠀",
  "⢀⠀⠀",
  "⡀⠀⠀",
  "⠄⠀⠀", // left edge, bottom → top …
  "⠂⠀⠀",
];

// Frames before the orbit repeats; useAnimatedTitle advances modulo this.
export const ORBIT_CYCLE = ORBIT_FRAMES.length;

// The 3-character spinner for a given tick.
export function tabSpinnerFrame(tick: number): string {
  return ORBIT_FRAMES[tick % ORBIT_CYCLE];
}
