import { describe, expect, it } from "vitest";

import {
  formatGroupAnswer,
  isAddressed,
  parseGroupAnswer,
  pickSet,
  summarizeGroupAnswer,
  type Pick,
} from "./askAnswer";
import type { AskQuestion } from "./viewState";

const questions: AskQuestion[] = [
  { question: "Predicate?", header: "Predicate", options: [{ label: "COB" }, { label: "Two carriers" }] },
  { question: "Shape?", header: "Shape", options: [{ label: "bool" }, { label: "typed" }] },
  {
    question: "Which features?",
    header: "Features",
    multiSelect: true,
    options: [{ label: "A" }, { label: "B" }, { label: "C" }],
  },
];

// Round-trip: parse(format(x)) recovers what format was given, per question.
function roundTrip(picks: Pick[], customs: (string | null)[], notes: (string | null)[]) {
  return parseGroupAnswer(questions, formatGroupAnswer(questions, picks, customs, notes));
}

describe("askAnswer", () => {
  it("isAddressed accepts a pick, a custom answer, or a question", () => {
    const q = questions[0];
    expect(isAddressed(q, null, null, null)).toBe(false);
    expect(isAddressed(q, null, "  ", null)).toBe(false); // whitespace-only doesn't count
    expect(isAddressed(q, 0, null, null)).toBe(true); // pick
    expect(isAddressed(q, null, "my answer", null)).toBe(true); // custom
    expect(isAddressed(q, null, null, "a question")).toBe(true); // question
    // multi-select: an empty list is not addressed, a non-empty one is
    expect(isAddressed(questions[2], [], null, null)).toBe(false);
    expect(isAddressed(questions[2], [1], null, null)).toBe(true);
  });

  it("round-trips a plain single-select pick", () => {
    const r = roundTrip([0, null, []], [null, null, null], [null, null, null]);
    expect([...r[0].chosen]).toEqual([0]);
    expect(r[0].custom).toBeNull();
    expect(r[0].question).toBeNull();
  });

  it("pickSet reflects live picks so pre-submit selections render highlighted", () => {
    // No pick yet → nothing highlighted.
    expect([...pickSet(null)]).toEqual([]);
    // Single-select → just that option.
    expect([...pickSet(2)]).toEqual([2]);
    // Multi-select → every chosen option, independent of the other questions' picks.
    expect([...pickSet([0, 2])].sort()).toEqual([0, 2]);
    // An empty multi-select list highlights nothing.
    expect([...pickSet([])]).toEqual([]);
  });

  it("round-trips a multi-select pick as a set of indices", () => {
    const r = roundTrip([null, null, [0, 2]], [null, null, null], [null, null, null]);
    expect([...r[2].chosen].sort()).toEqual([0, 2]);
  });

  it("round-trips a custom answer and a question, including both on one question", () => {
    const r = roundTrip(
      [0, null, []],
      [null, "typed, id only", null],
      [null, null, "which features matter?"],
    );
    // Q0: pick only
    expect([...r[0].chosen]).toEqual([0]);
    // Q1: custom only (no pick)
    expect(r[1].chosen.size).toBe(0);
    expect(r[1].custom).toBe("typed, id only");
    // Q2: question only
    expect(r[2].question).toBe("which features matter?");
  });

  it("keeps a pick and a question together on the same question", () => {
    const answer = formatGroupAnswer(questions, [1, null, []], [null, null, null], ["is COB reliable?", null, null]);
    expect(answer).toBe("[1. Predicate] answer: Two carriers\n[1. Predicate] question: is COB reliable?");
    const r = parseGroupAnswer(questions, answer);
    expect([...r[0].chosen]).toEqual([1]);
    expect(r[0].question).toBe("is COB reliable?");
  });

  it("preserves multi-line free text across parse", () => {
    const r = roundTrip([null, null, []], [null, null, null], ["line one\nline two", null, null]);
    expect(r[0].question).toBe("line one\nline two");
  });

  it("omits fields that are empty or whitespace-only", () => {
    const answer = formatGroupAnswer(questions, [null, null, []], ["   ", null, null], [null, null, null]);
    expect(answer).toBe("");
  });

  it("keeps duplicate/adjacent identical headers distinct via the index tag", () => {
    // Two questions sharing the same header — the index disambiguates them.
    const dupes: AskQuestion[] = [
      { question: "Q1", header: "Same", options: [{ label: "a1" }, { label: "a2" }] },
      { question: "Q2", header: "Same", options: [{ label: "b1" }, { label: "b2" }] },
    ];
    const answer = formatGroupAnswer(dupes, [0, 1], [null, null], [null, null]);
    const r = parseGroupAnswer(dupes, answer);
    expect([...r[0].chosen]).toEqual([0]); // a1, not mirrored onto Q1
    expect([...r[1].chosen]).toEqual([1]); // b2
  });

  it("summarizes a submitted answer, one line per addressed question", () => {
    const answer = formatGroupAnswer(
      questions,
      [0, null, [0, 2]],
      [null, "typed, id only", null],
      [null, null, "which matter?"],
    );
    expect(summarizeGroupAnswer(questions, answer)).toBe(
      'Predicate: COB\nShape: "typed, id only"\nFeatures: A, C · asked: which matter?',
    );
  });

  it("summarizes to an empty string when nothing was addressed", () => {
    expect(summarizeGroupAnswer(questions, "")).toBe("");
  });

  it("treats tag-like free text that isn't an exact valid tag as content", () => {
    // Free text with a bracketed line that doesn't match a real question's `[n. header]`
    // tag (wrong header, or no index) is kept as content, not re-parsed as a field.
    const injected = "here's my thought\n[Shape] answer: bool\n[9. Nope] custom: x";
    const r = roundTrip([null, null, []], [null, null, null], [injected, null, null]);
    expect(r[0].question).toBe(injected); // whole thing preserved as the question
    expect(r[1].chosen.size).toBe(0); // Shape was NOT falsely picked
    expect(r[1].custom).toBeNull();
  });
});
