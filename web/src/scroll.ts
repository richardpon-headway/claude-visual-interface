// How close to the bottom (in px) still counts as "pinned" — small slack so a few
// stray pixels or sub-pixel rounding don't read as "scrolled up".
export const BOTTOM_SLACK_PX = 40;

// Whether a scroll container is at (or within `slackPx` of) its bottom. Pure so the
// stick-to-bottom decision is unit-testable without a real layout — jsdom reports
// scrollHeight/clientHeight as 0, so the DOM wiring is verified manually instead.
export function isNearBottom(
  el: { scrollTop: number; scrollHeight: number; clientHeight: number },
  slackPx: number,
): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= slackPx;
}
