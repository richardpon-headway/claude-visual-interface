// The braille spinner frames used by the in-app ThinkingIndicator, plus the tick cadence
// shared by both busy indicators. BRAILLE_FRAMES is in-app only; the browser-tab title
// uses a three-cell braille orbit spinner instead (see tabSpinner.ts), but both tick at
// SPINNER_TICK_MS so their cadence stays in step.
export const BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
export const SPINNER_TICK_MS = 120;
