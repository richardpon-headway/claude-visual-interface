import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityFeed } from "./ActivityFeed";

describe("ActivityFeed", () => {
  it("shows a placeholder when there's no activity", () => {
    render(<ActivityFeed activity={[]} />);
    expect(screen.getByText(/no activity yet/i)).toBeInTheDocument();
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
});
