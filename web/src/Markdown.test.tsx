import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Markdown } from "./Markdown";

describe("Markdown", () => {
  it("renders bold, lists, and inline code", () => {
    const { container } = render(
      <Markdown>{"**bold** text\n\n- one\n- two\n\n`code`"}</Markdown>,
    );
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("code")?.textContent).toBe("code");
  });

  it("renders GFM tables", () => {
    render(<Markdown>{"| A | B |\n| - | - |\n| 1 | 2 |"}</Markdown>);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("opens links in a new tab", () => {
    render(<Markdown>{"[site](https://example.com)"}</Markdown>);
    const link = screen.getByRole("link", { name: "site" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("highlights fenced code blocks", () => {
    const { container } = render(
      <Markdown>{"```js\nconst x = 1;\n```"}</Markdown>,
    );
    // rehype-highlight tags the <code> with hljs classes.
    expect(container.querySelector("code.hljs")).toBeInTheDocument();
  });
});
