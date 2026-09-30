// Compose the browser-tab title from the session's base title and its two tab-level
// cues. Precedence is "working beats done": while anything is still working the caller
// passes a spinner frame and it wins; only once the session is fully idle do the
// turn-end waves show. The two never both prefix the title.
//
// The overlap is real: the waves flag is set on the falling edge of the foreground turn
// (useTabTurnEndIndicator) while a background task can still be running, so `frame` and
// `wavesUnseen` can both be truthy at the same instant. Resolving it here — rather than
// in the hook — keeps useTabTurnEndIndicator untouched.
export function composeTitle(base: string, frame: string | null, wavesUnseen: boolean): string {
  if (frame !== null) return `${frame} ${base}`;
  if (wavesUnseen) return `\u{1F44B}\u{1F44B}\u{1F44B} ${base}`;
  return base;
}
