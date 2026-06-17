import { useEffect, useState } from "react";

// A braille spinner + a cycling word + an elapsed-seconds counter, shown while an
// agent turn is in flight — echoing the Claude CLI's "thinking" feel.
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const WORDS = ["Thinking", "Pondering", "Cogitating", "Noodling", "Mulling", "Ruminating"];
const TICK_MS = 120;
// The whimsical word changes only every few seconds (the spinner still ticks fast),
// matching the Claude CLI's cadence.
const WORD_INTERVAL_MS = 4000;

export function ThinkingIndicator({ active }: { active: boolean }) {
  // Elapsed ms since `active` flipped true; a single interval drives the spinner,
  // the word cycle, and the seconds counter. Reset and cleared whenever inactive.
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!active) return;
    const start = Date.now();
    setElapsed(0);
    const id = setInterval(() => setElapsed(Date.now() - start), TICK_MS);
    return () => clearInterval(id);
  }, [active]);

  if (!active) return null;

  const frame = FRAMES[Math.floor(elapsed / TICK_MS) % FRAMES.length];
  const word = WORDS[Math.floor(elapsed / WORD_INTERVAL_MS) % WORDS.length];
  const seconds = Math.floor(elapsed / 1000);

  // Inline content only — the parent (Surface) provides the bordered row so
  // the Stop button can sit on the same line.
  return (
    <span className="flex items-center gap-2">
      <span className="font-mono text-sky-300">{frame}</span>
      <span>
        {word}… <span className="text-zinc-500">({seconds}s)</span>
      </span>
    </span>
  );
}
