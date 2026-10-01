// A three-bar "equalizer" rendered in Unicode block glyphs, used as the browser-tab
// busy indicator while the session is working. A tab title is plain text — it can't
// render real animated bars — so this is the text stand-in for an equalizer.
//
// The in-app ThinkingIndicator keeps its braille spinner (see braille.ts); only the
// tab title uses this, so the two are intentionally different and do not share frames.

// Block glyphs shortest → tallest; a bar rises and falls through these like a VU meter.
export const EQ_LEVELS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇"];

// Up-then-down traversal of EQ_LEVELS (indices), so each bar bounces smoothly instead
// of snapping from tallest back to shortest. Period = 12 ticks.
const BOUNCE = [0, 1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1];

// Each of the three bars starts at a different point in the bounce so they're never in
// phase — at any tick the three heights differ (they are never all equal), which is the
// "not synchronized" look. Verified exhaustively in tabEqualizer.test.ts.
const BAR_PHASES = [0, 4, 8];

// Number of ticks before the whole pattern repeats; useAnimatedTitle advances modulo this.
export const EQ_CYCLE = BOUNCE.length;

// The 3-character equalizer string for a given tick (e.g. "▁▅▅", "▂▆▃", …).
export function tabEqualizerFrame(tick: number): string {
  return BAR_PHASES.map((phase) => EQ_LEVELS[BOUNCE[(tick + phase) % EQ_CYCLE]]).join("");
}
