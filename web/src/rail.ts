// Outline-rail helpers: deriving prompt landmarks from the conversation and the
// scroll-spy selection. Kept pure so the selection logic is unit-testable without
// a layout engine.

import type { ActivityEntry } from "./viewState";

export type Prompt = { id: string; text: string };
export type PromptPos = { id: string; top: number };

// One landmark per user prompt, in order. The id is stable for the surface lifetime
// (the Nth user prompt is always `prompt-N`), so the rail and the rendered anchors
// agree regardless of which non-prompt rows are filtered from the transcript.
export function promptLandmarks(activity: ActivityEntry[]): Prompt[] {
  const prompts: Prompt[] = [];
  let n = 0;
  for (const entry of activity) {
    if (entry.kind === "user") {
      prompts.push({ id: `prompt-${n}`, text: entry.text });
      n += 1;
    }
  }
  return prompts;
}

// The active prompt is the last one scrolled to/above the marker line; before any
// prompt has reached it, the first prompt is active. `top` values are viewport-
// relative offsets from the scroll container's top.
export function activePromptId(prompts: PromptPos[], marker = 80): string | null {
  if (prompts.length === 0) return null;
  let active = prompts[0].id;
  for (const p of prompts) {
    if (p.top <= marker) active = p.id;
    else break;
  }
  return active;
}
