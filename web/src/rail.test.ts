import { describe, expect, it } from "vitest";

import { activePromptId, promptLandmarks } from "./rail";

describe("promptLandmarks", () => {
  it("derives one stable landmark per user prompt, in order", () => {
    const prompts = promptLandmarks([
      { kind: "user", text: "first", summary: "the first ask" },
      { kind: "text", text: "answer" },
      { kind: "tool", text: "Bash" },
      { kind: "user", text: "second" },
    ]);
    expect(prompts).toEqual([
      { id: "prompt-0", text: "first", summary: "the first ask" },
      { id: "prompt-1", text: "second", summary: null },
    ]);
  });

  it("is empty with no prompts", () => {
    expect(promptLandmarks([{ kind: "text", text: "x" }])).toEqual([]);
  });
});

describe("activePromptId", () => {
  const prompts = [
    { id: "prompt-0", top: -300 },
    { id: "prompt-1", top: 40 },
    { id: "prompt-2", top: 600 },
  ];

  it("picks the last prompt at/above the marker", () => {
    expect(activePromptId(prompts)).toBe("prompt-1");
  });

  it("falls back to the first prompt before any has passed the marker", () => {
    expect(
      activePromptId([
        { id: "prompt-0", top: 200 },
        { id: "prompt-1", top: 500 },
      ]),
    ).toBe("prompt-0");
  });

  it("returns null with no prompts", () => {
    expect(activePromptId([])).toBeNull();
  });
});
