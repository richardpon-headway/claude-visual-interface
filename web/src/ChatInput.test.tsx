import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "./ChatInput";

describe("ChatInput", () => {
  it("sends the trimmed text on submit and clears the box", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const input = screen.getByRole("textbox", { name: /message the agent/i });
    fireEvent.change(input, { target: { value: "  review the diff  " } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledWith("review the diff");
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("does not send blank input", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    fireEvent.change(screen.getByRole("textbox", { name: /message the agent/i }), {
      target: { value: "   " },
    });
    fireEvent.submit(screen.getByRole("textbox", { name: /message the agent/i }).closest("form")!);
    expect(onSend).not.toHaveBeenCalled();
  });
});
