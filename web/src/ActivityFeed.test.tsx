import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityFeed } from "./ActivityFeed";

describe("ActivityFeed", () => {
  it("shows a placeholder when there's no activity", () => {
    render(<ActivityFeed activity={[]} surface="s" />);
    expect(screen.getByText(/ask anything to get started/i)).toBeInTheDocument();
  });

  it("hides successful run results but keeps failures", () => {
    render(
      <ActivityFeed
        activity={[
          { kind: "result", text: "success" },
          { kind: "result", text: "stopped" },
        ]}
        surface="s"
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
        surface="s"
      />,
    );
    expect(screen.getByText("reviewing the diff")).toBeInTheDocument();
    expect(screen.getByText("Bash")).toBeInTheDocument();
    expect(screen.getByText("tool")).toBeInTheDocument();
  });

  it("renders an artifact entry as an inline iframe", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "artifact", text: "design", html: "<p>hi</p>" }]} surface="s" />,
    );
    const iframe = container.querySelector("iframe");
    expect(iframe).toBeInTheDocument();
    expect(iframe).toHaveAttribute("srcdoc", "<p>hi</p>");
  });

  it("renders a file entry as a diff block with an expand control", () => {
    render(
      <ActivityFeed
        activity={[{ kind: "file", text: "src/a.ts", diff: "@@ -1 +1 @@\n-old\n+new" }]}
        surface="s"
      />,
    );
    expect(screen.getByText("src/a.ts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand to full file/i })).toBeInTheDocument();
  });

  it("renders a user turn as a right-aligned bubble", () => {
    const { container } = render(
      <ActivityFeed activity={[{ kind: "user", text: "open utils.py" }]} surface="s" />,
    );
    expect(screen.getByText("open utils.py")).toBeInTheDocument();
    expect(container.querySelector("li.justify-end")).toBeInTheDocument();
  });
});
