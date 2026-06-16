import { useEffect, useState } from "react";

// A braille spinner + a cycling word + an elapsed-seconds counter, shown while an
// agent turn is in flight — echoing the Claude CLI's "thinking" feel.
const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const WORDS = ["Thinking", "Pondering", "Cogitating", "Noodling", "Mulling", "Ruminating"];
const TICK_MS = 120;

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
  const word = WORDS[Math.floor(elapsed / 1500) % WORDS.length];
  const seconds = Math.floor(elapsed / 1000);

  return (
    <div className="flex items-center gap-2 border-t border-zinc-800 px-3 py-1.5 text-xs text-zinc-400">
      <span className="font-mono text-sky-300">{frame}</span>
      <span>
        {word}… <span className="text-zinc-500">({seconds}s)</span>
      </span>
    </div>
  );
}
