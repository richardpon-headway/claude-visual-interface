// The AskUserQuestion picker lets the user address each question three independent
// ways: pick a predefined option, write a custom answer, or ask the agent a question
// about it (any combination). All three are folded into ONE answer string that rides
// the existing free-text answer path (the SDK's AskUserQuestion returns nothing to the
// model — the answer comes back as the next user turn), so no wire/schema change is
// needed. This module owns that string's format: `formatGroupAnswer` builds it on
// submit, `parseGroupAnswer` reconstructs it for the locked/answered re-render after a
// reload (when the component's local state is gone and only the persisted string
// survives). Keeping build and parse together stops the two from drifting.

import type { AskQuestion } from "./viewState";

// A pick per question: a single chosen option index (or null), or a sorted list of
// indices for a multi-select question.
export type Pick = number | number[] | null;

// The set of option indices a live pick represents — a single index, a multi-select
// list, or nothing. Used to render the picker's highlight from live state before the
// group is submitted (once submitted, the committed answer string drives the highlight).
export function pickSet(pick: Pick): Set<number> {
  if (pick === null) return new Set();
  return new Set(Array.isArray(pick) ? pick : [pick]);
}

// What one question resolved to, recovered from the answer string.
export type QuestionResponse = {
  chosen: Set<number>; // option indices the user picked
  custom: string | null; // free-text custom answer, if any
  question: string | null; // free-text question to the agent, if any
};

// The label that anchors a question in the answer string. Mirrors the picker's own
// header/question fallback so build and parse agree.
function labelFor(q: AskQuestion): string {
  return q.header || q.question;
}

// Whether a question has been "addressed" — the submit gate. A pick, a non-empty
// custom answer, or a non-empty question each count; any combination is fine.
export function isAddressed(
  q: AskQuestion,
  pick: Pick,
  custom: string | null,
  note: string | null,
): boolean {
  const hasPick = q.multiSelect ? (pick as number[]).length > 0 : pick !== null;
  return hasPick || !!custom?.trim() || !!note?.trim();
}

// Build the answer string sent back as the turn. One line per (question, field), each
// tagged with the question's 1-based index AND header:
//   [1. Header] answer: Option A, Option B
//   [1. Header] custom: my own answer
//   [1. Header] question: what about X?
// A question emits only the fields it has. The index makes each line map to exactly one
// question, so duplicate/adjacent identical headers, and free text that merely looks
// like a marker, don't confuse the parser. Free text with embedded newlines keeps its
// tag on the first line only; continuation lines carry no tag and are re-joined on parse.
export function formatGroupAnswer(
  questions: AskQuestion[],
  picks: Pick[],
  customs: (string | null)[],
  notes: (string | null)[],
): string {
  const lines: string[] = [];
  questions.forEach((q, qi) => {
    const tag = `[${qi + 1}. ${labelFor(q)}]`;
    const p = picks[qi];
    const picked = q.multiSelect
      ? (p as number[]).map((i) => q.options[i].label)
      : p !== null
        ? [q.options[p as number].label]
        : [];
    if (picked.length) lines.push(`${tag} answer: ${picked.join(", ")}`);
    const custom = customs[qi]?.trim();
    if (custom) lines.push(`${tag} custom: ${custom}`);
    const note = notes[qi]?.trim();
    if (note) lines.push(`${tag} question: ${note}`);
  });
  return lines.join("\n");
}

const FIELD_LINE = /^\[(\d+)\. (.+?)\] (answer|custom|question): (.*)$/;

// Reconstruct per-question responses from the answer string, best-effort. Used only to
// re-render an answered card after reload; a miss degrades to "no highlight / no text",
// never a throw. A line is only treated as a field start when its index is in range AND
// its header matches that question — otherwise (e.g. free text that happens to look like
// a tag) it's appended to the current field, so multi-line custom answers / questions
// survive intact.
export function parseGroupAnswer(questions: AskQuestion[], answer: string): QuestionResponse[] {
  const fields = questions.map(
    () => ({}) as { answer?: string; custom?: string; question?: string },
  );
  let cur: { qi: number; field: "answer" | "custom" | "question" } | null = null;

  for (const line of answer.split("\n")) {
    const m = line.match(FIELD_LINE);
    const qi = m ? Number(m[1]) - 1 : -1;
    if (m && qi >= 0 && qi < questions.length && m[2] === labelFor(questions[qi])) {
      const field = m[3] as "answer" | "custom" | "question";
      fields[qi][field] = m[4];
      cur = { qi, field };
    } else if (cur) {
      // Continuation of the previous field (e.g. a multi-line question).
      fields[cur.qi][cur.field] = `${fields[cur.qi][cur.field] ?? ""}\n${line}`;
    }
  }

  return questions.map((q, qi) => {
    const bucket = fields[qi];
    const chosen = new Set<number>();
    if (bucket.answer !== undefined) {
      const parts = q.multiSelect ? bucket.answer.split(", ") : [bucket.answer];
      q.options.forEach((o, oi) => {
        if (parts.includes(o.label)) chosen.add(oi);
      });
    }
    return {
      chosen,
      custom: bucket.custom ?? null,
      question: bucket.question ?? null,
    };
  });
}
