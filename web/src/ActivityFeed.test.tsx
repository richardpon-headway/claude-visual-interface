import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityFeed } from "./ActivityFeed";

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

  it("renders each entry and labels tool calls", () => {
    render(
      <ActivityFeed
        activity={[
          { kind: "text", text: "reviewing the diff" },
          { kind: "tool", text: "Bash" },
        ]}
      />,
    );
    expect(screen.getByText("reviewing the diff")).toBeInTheDocument();
    expect(screen.getByText("Bash")).toBeInTheDocument();
    expect(screen.getByText("tool")).toBeInTheDocument();
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
});
