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

  it("renders an artifact entry as an inline iframe with the dark surface + scale defaults", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "artifact", text: "design", html: "<p>hi</p>" }]} />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe).toBeInTheDocument();
    const srcdoc = iframe!.getAttribute("srcdoc")!;
    // The author's content is preserved verbatim...
    expect(srcdoc).toContain("<p>hi</p>");
    // ...and the app injects the scale-match zoom and a dark surface that reliably wins.
    expect(srcdoc).toContain("zoom:1.25");
    expect(srcdoc).toMatch(/background:\s*#09090b\s*!important/i);
  });

  it("leaves a data-theme=\"light\" mockup in its own colors (no forced dark background)", () => {
    const html =
      '<html data-theme="light"><head></head><body style="background:#fff">mock</body></html>';
    const { container } = render(
      <ActivityFeed activity={[{ kind: "artifact", text: "mock", html }]} />,
    );
    const srcdoc = container.querySelector("iframe")!.getAttribute("srcdoc")!;
    // Scale still matches the app, but no dark background is forced on the mockup.
    expect(srcdoc).toContain("zoom:1.25");
    expect(srcdoc).not.toContain("!important");
  });

  it("does not crash when the iframe document isn't parsed yet (null documentElement)", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "artifact", text: "x", html: "<p>hi</p>" }]} />,
    );
    const iframe = container.querySelector("iframe")!;
    // Reproduce a real browser's pre-parse state: contentDocument exists but its
    // documentElement is still null. Before the guard, the load handler's
    // getBoundingClientRect read threw here and blanked the whole app.
    Object.defineProperty(iframe, "contentDocument", {
      configurable: true,
      get: () => ({ documentElement: null }) as unknown as Document,
    });
    expect(() => fireEvent.load(iframe)).not.toThrow();
    // The artifact survived — no boundary fallback.
    expect(container.querySelector("iframe")).toBeInTheDocument();
    expect(screen.queryByText(/couldn't render this artifact/i)).toBeNull();
  });

  it("renders a user turn as a right-aligned bubble", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "user", text: "open utils.py" }]} />,
    );
    expect(screen.getByText("open utils.py")).toBeInTheDocument();
    expect(container.querySelector("li.items-end")).toBeInTheDocument();
  });

  it("renders a user turn's screenshots as images served from /screenshots", () => {
    const { container } = render(
      <ActivityFeed
        activity={[{ kind: "user", text: "what's this?", images: ["abc.webp", "def.webp"] }]}
      />,
    );
    const imgs = container.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0]).toHaveAttribute("src", "/screenshots/abc.webp");
  });

  it("shows a placeholder when a screenshot image fails to load", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "user", text: "", images: ["gone.webp"] }]} />,
    );
    fireEvent.error(container.querySelector("img")!);
    expect(screen.getByText("screenshot no longer available")).toBeInTheDocument();
    expect(container.querySelector("img")).not.toBeInTheDocument();
  });

  it("renders an image-only user turn without an empty text bubble", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "user", text: "", images: ["solo.webp"] }]} />,
    );
    expect(container.querySelector("img")).toBeInTheDocument();
    // No bubble div (the zinc-800 rounded bubble) when there's no text.
    expect(container.querySelector("div.bg-zinc-800")).not.toBeInTheDocument();
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
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "[1. Approach] answer: Custom modal");
  });

  it("single-select: a number key selects and sends", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.keyDown(window, { key: "2" });
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "[1. Approach] answer: Native");
  });

  it("multi-select: Space toggles and Enter submits the joined labels", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[multiAsk]} onAnswer={onAnswer} />);
    fireEvent.keyDown(window, { key: " " }); // toggles the cursor's option (A)
    fireEvent.keyDown(window, { key: "ArrowDown" });
    fireEvent.keyDown(window, { key: " " }); // toggles B
    expect(onAnswer).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onAnswer).toHaveBeenCalledWith("ask-2", "[1. Features] answer: A, B");
  });

  const twoQuestions: ActivityEntry = {
    kind: "ask",
    text: "AskUserQuestion",
    ask_id: "ask-3",
    questions: [
      { question: "Q1", header: "One", options: [{ label: "a1" }, { label: "a2" }] },
      { question: "Q2", header: "Two", options: [{ label: "b1" }, { label: "b2" }] },
    ],
  };

  it("does not send until every question in a multi-question call is answered", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[twoQuestions]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("a1"));
    expect(onAnswer).not.toHaveBeenCalled(); // Q2 still open
    fireEvent.click(screen.getByText("b2"));
    expect(onAnswer).toHaveBeenCalledWith("ask-3", "[1. One] answer: a1\n[2. Two] answer: b2");
  });

  it("wraps the questions in one group container with a shared header", () => {
    render(<ActivityFeed activity={[twoQuestions]} onAnswer={vi.fn()} />);
    expect(screen.getByText(/2 questions/)).toBeInTheDocument();
    expect(screen.getByText(/answer all to continue/)).toBeInTheDocument();
  });

  it("a custom answer alone addresses a question and is sent labeled", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("+ custom answer"));
    fireEvent.change(screen.getByLabelText("Custom answer for Approach"), {
      target: { value: "a hybrid" },
    });
    fireEvent.click(screen.getByText(/Send group/));
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "[1. Approach] custom: a hybrid");
  });

  it("opening a text affordance suppresses single-select auto-submit; Send commits", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("+ custom answer")); // opens an (empty) textarea
    fireEvent.click(screen.getByText("Custom modal")); // pick — no longer auto-submits
    expect(onAnswer).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText(/Send group/));
    expect(onAnswer).toHaveBeenCalledWith("ask-1", "[1. Approach] answer: Custom modal");
  });

  it("a pick and a question about the same question coexist in the answer", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[singleAsk]} onAnswer={onAnswer} />);
    fireEvent.click(screen.getByText("+ ask about this"));
    fireEvent.change(screen.getByLabelText("Question about Approach"), {
      target: { value: "which is faster?" },
    });
    fireEvent.click(screen.getByText("Custom modal"));
    fireEvent.click(screen.getByText(/Send group/));
    expect(onAnswer).toHaveBeenCalledWith(
      "ask-1",
      "[1. Approach] answer: Custom modal\n[1. Approach] question: which is faster?",
    );
  });

  it("multi-select Send stays disabled until the question is addressed", () => {
    render(<ActivityFeed activity={[multiAsk]} onAnswer={vi.fn()} />);
    const send = screen.getByText(/Send group/).closest("button")!;
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByText("A"));
    expect(send).not.toBeDisabled();
  });

  it("locked reload shows custom-answer and question text from the persisted string", () => {
    render(
      <ActivityFeed
        activity={[
          {
            ...singleAsk,
            answer: "[1. Approach] custom: a hybrid\n[1. Approach] question: which is faster?",
          },
        ]}
        onAnswer={vi.fn()}
      />,
    );
    expect(screen.getByText("a hybrid")).toBeInTheDocument();
    expect(screen.getByText("which is faster?")).toBeInTheDocument();
    expect(screen.getByText("Custom answer")).toBeInTheDocument();
    expect(screen.getByText("Question")).toBeInTheDocument();
    // No affordance chips in the locked state.
    expect(screen.queryByText("+ custom answer")).toBeNull();
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

  const previewAsk: ActivityEntry = {
    kind: "ask",
    text: "AskUserQuestion: Which fix?",
    ask_id: "ask-p",
    questions: [
      {
        question: "Which fix?",
        header: "Fix",
        options: [
          { label: "Guard test", preview: "<h3>Guard test</h3><p>add a FE guard</p>" },
          { label: "Derive", preview: "<h3>Derive</h3><p>compute on the FE</p>" },
        ],
      },
    ],
  };

  it("renders an option's rich preview as a sandboxed iframe with the CVI defaults", () => {
    const { container } = render(<ActivityFeed activity={[previewAsk]} />);
    const iframes = container.querySelectorAll("iframe");
    // One sandboxed preview per option, carrying the author's content + injected scale.
    expect(iframes.length).toBe(2);
    const srcdoc = iframes[0].getAttribute("srcdoc")!;
    expect(srcdoc).toContain("add a FE guard");
    expect(srcdoc).toContain("zoom:1.25");
    // Script-free: the frame gets allow-same-origin only (never allow-scripts).
    expect(iframes[0].getAttribute("sandbox")).toBe("allow-same-origin");
  });

  it("rich single-select: clicking Select sends the label-formatted answer", () => {
    const onAnswer = vi.fn();
    render(<ActivityFeed activity={[previewAsk]} onAnswer={onAnswer} />);
    // The label lives in the preview HTML (inside the iframe) and on the button's
    // aria-label; clicking Select still sends the clean label as the answer.
    fireEvent.click(screen.getByLabelText("Select Derive"));
    expect(onAnswer).toHaveBeenCalledWith("ask-p", "[1. Fix] answer: Derive");
  });

  it("renders a locked answered state from a persisted answer, keeping all options", () => {
    const onAnswer = vi.fn();
    render(
      <ActivityFeed
        activity={[{ ...singleAsk, answer: "[1. Approach] answer: Custom modal" }]}
        onAnswer={onAnswer}
      />,
    );
    // Both the chosen option AND the unchosen alternatives stay on screen so the
    // original context is still readable after answering.
    expect(screen.getByText("Custom modal")).toBeInTheDocument();
    expect(screen.getByText("Native")).toBeInTheDocument(); // unchosen option still shown
    expect(screen.getByText(/answered/)).toBeInTheDocument();
    // The option buttons are locked (disabled) — you can't re-answer.
    const chosenBtn = screen.getByText("Custom modal").closest("button")!;
    const otherBtn = screen.getByText("Native").closest("button")!;
    expect(chosenBtn).toBeDisabled();
    expect(otherBtn).toBeDisabled();
    // A stray key can't re-answer a locked picker either.
    fireEvent.keyDown(window, { key: "2" });
    expect(onAnswer).not.toHaveBeenCalled();
    fireEvent.click(otherBtn);
    expect(onAnswer).not.toHaveBeenCalled();
  });
});
