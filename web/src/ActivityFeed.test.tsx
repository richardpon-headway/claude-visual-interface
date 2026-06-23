import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ActivityFeed } from "./ActivityFeed";
import type { ActivityEntry } from "./viewState";

const singleAsk: ActivityEntry = {
  kind: "ask",
  text: "AskUserQuestion: Which approach?",
  ask_id: "ask-1",
  questions: [
    {
      question: "Which approach?",
      header: "Approach",
      options: [{ label: "Custom modal" }, { label: "Native" }],
    },
  ],
};

const multiAsk: ActivityEntry = {
  kind: "ask",
  text: "AskUserQuestion: Which features?",
  ask_id: "ask-2",
  questions: [
    {
      question: "Which features?",
      header: "Features",
      multiSelect: true,
      options: [{ label: "A" }, { label: "B" }, { label: "C" }],
    },
  ],
};

describe("ActivityFeed", () => {
  it("shows a placeholder when there's no activity", () => {
    render(<ActivityFeed activity={[]} />);
    expect(screen.getByText(/ask anything to get started/i)).toBeInTheDocument();
  });

  it("hides successful run results but keeps failures", () => {
    render(
      <ActivityFeed
        activity={[
          { kind: "result", text: "success" },
          { kind: "result", text: "stopped" },
        ]}
      />,
    );
    expect(screen.queryByText("success")).toBeNull();
    expect(screen.getByText("stopped")).toBeInTheDocument();
  });

  it("collapses a turn's tool calls into a single count bar when settled", () => {
    render(
      <ActivityFeed
        activity={[
          { kind: "user", text: "go" },
          { kind: "text", text: "reviewing the diff" },
          { kind: "tool", text: "Bash grep" },
          { kind: "tool", text: "Read foo.py" },
        ]}
      />,
    );
    expect(screen.getByText("reviewing the diff")).toBeInTheDocument();
    // The two tool calls fold into one bar; individual call text is hidden when settled.
    expect(screen.getByText("2 tool calls")).toBeInTheDocument();
    expect(screen.queryByText("Bash grep")).toBeNull();
    expect(screen.queryByText("Read foo.py")).toBeNull();
  });

  it("uses a singular label for a single tool call", () => {
    render(<ActivityFeed activity={[{ kind: "user", text: "go" }, { kind: "tool", text: "Bash" }]} />);
    expect(screen.getByText("1 tool call")).toBeInTheDocument();
  });

  it("shows the live count and the latest call while the turn is in flight", () => {
    render(
      <ActivityFeed
        thinking
        activity={[
          { kind: "user", text: "go" },
          { kind: "tool", text: "Bash grep" },
          { kind: "tool", text: "Read foo.py" },
        ]}
      />,
    );
    expect(screen.getByText("2 tool calls")).toBeInTheDocument();
    expect(screen.getByText("Read foo.py")).toBeInTheDocument();
  });

  it("renders an artifact entry as an inline iframe", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "artifact", text: "design", html: "<p>hi</p>" }]} />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute("srcdoc", "<p>hi</p>");
  });

  it("renders a user turn as a right-aligned bubble", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "user", text: "open utils.py" }]} />,
    );
    expect(screen.getByText("open utils.py")).toBeInTheDocument();
    expect(container.querySelector("li.justify-end")).toBeInTheDocument();
  });

  it("renders an ask entry as a question card with its options", () => {
    render(
      <ActivityFeed
        activity={[
          {
            kind: "ask",
            text: "AskUserQuestion: Which approach?",
            ask_id: "ask-1",
            questions: [
              {
                question: "Which approach?",
                header: "Approach",
                options: [{ label: "Custom modal", description: "themed" }, { label: "Native" }],
              },
            ],
          },
        ]}
      />,
    );
    expect(screen.getByText("Which approach?")).toBeInTheDocument();
    expect(screen.getByText("Custom modal")).toBeInTheDocument();
    expect(screen.getByText("Native")).toBeInTheDocument();
    expect(screen.getByText("Approach")).toBeInTheDocument();
  });

  it("falls back to a plain line for an ask entry with no structured questions", () => {
    render(<ActivityFeed activity={[{ kind: "ask", text: "AskUserQuestion: pick one" }]} />);
    expect(screen.getByText("AskUserQuestion: pick one")).toBeInTheDocument();
  });

  it("single-select: clicking an option sends the formatted answer", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("Custom modal"));
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "Approach: Custom modal");
  });

  it("single-select: a number key selects and sends", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.keyDown(window, { key: "2" });
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "Approach: Native");
  });

  it("multi-select: Space toggles and Enter submits the joined labels", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[multiAsk]} onAnswer={onAnswer} />);
    fireEvent.keyDown(window, { key: " " }); // toggles the cursor's option (A)
    fireEvent.keyDown(window, { key: "ArrowDown" });
    fireEvent.keyDown(window, { key: " " }); // toggles B
    expect(onAnswer).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onAnswer).toHaveBeenCalledWith("ask-2", "Features: A, B");
  });

  it("does not send until every question in a multi-question call is answered", () => {
    const onAnswer = vi.fn();
    const twoQuestions: ActivityEntry = {
      kind: "ask",
      text: "AskUserQuestion",
      ask_id: "ask-3",
      questions: [
        { question: "Q1", header: "One", options: [{ label: "a1" }, { label: "a2" }] },
        { question: "Q2", header: "Two", options: [{ label: "b1" }, { label: "b2" }] },
      ],
    };
    render(<ActivityFeed activity={[twoQuestions]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("a1"));
    expect(onAnswer).not.toHaveBeenCalled(); // Q2 still open
    fireEvent.click(screen.getByText("b2"));
    expect(onAnswer).toHaveBeenCalledWith("ask-3", "One: a1\nTwo: b2");
  });

  it("ignores keyboard while the composer is focused", () => {
    const onAnswer = vi.fn();
    render(
      <div>
        <textarea aria-label="composer" />
        <ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />
      </div>,
    );
    screen.getByLabelText("composer").focus();
    fireEvent.keyDown(window, { key: "1" });
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("renders a locked answered state from a persisted answer", () => {
    const onAnswer = vi.fn();
    render(
      <ActivityFeed
        activity={[{ ...singleAsk, answer: "Approach: Custom modal" }]}
        onAnswer={onAnswer}
      />,
    );
    expect(screen.getByText("Custom modal")).toBeInTheDocument();
    expect(screen.queryByText("Native")).toBeNull(); // unchosen option not offered
    expect(screen.getByText(/answered/)).toBeInTheDocument();
    // A stray key can't re-answer a locked picker.
    fireEvent.keyDown(window, { key: "2" });
    expect(onAnswer).not.toHaveBeenCalled();
  });
});
