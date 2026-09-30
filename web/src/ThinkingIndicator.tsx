import { useEffect, useState } from "react";

import { BRAILLE_FRAMES, SPINNER_TICK_MS } from "./braille";

// A braille spinner + a cycling word + an elapsed-seconds counter, shown while an
// agent turn is in flight — echoing the Claude CLI's "thinking" feel.
const WORDS = ["Thinking", "Pondering", "Cogitating", "Noodling", "Mulling", "Ruminating"];
// The whimsical word changes only every few seconds (the spinner still ticks fast),
// matching the Claude CLI's cadence.
const WORD_INTERVAL_MS = 4000;

// `label`, when given, shows a fixed word instead of the cycling whimsical set — used
// for the "working in background" state so it reads distinctly from a normal in-flight turn.
export function ThinkingIndicator({ active, label }: { active: boolean; label?: string }) {
  // Elapsed ms since `active` flipped true; a single interval drives the spinner,
  // the word cycle, and the seconds counter. Reset and cleared whenever inactive.
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) return;
    const start = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Date.now() - start), SPINNER_TICK_MS);
    return () => clearInterval(id);
  }, [active]);

  if (!active) return null;

  const frame = BRAILLE_FRAMES[Math.floor(elapsed / SPINNER_TICK_MS) % BRAILLE_FRAMES.length];
  const word = label ?? WORDS[Math.floor(elapsed / WORD_INTERVAL_MS) % WORDS.length];
  const seconds = Math.floor(elapsed / 1000);

  // Inline content only — the parent (Surface) provides the status row above
  // the composer.
  return (
    <span className="flex items-center gap-2">
      <span className="font-mono text-sky-300">{frame}</span>
      <span>
        {word}… <span className="text-zinc-500">({seconds}s)</span>
      </span>
    </span>
  );
}
