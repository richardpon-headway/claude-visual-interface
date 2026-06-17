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

    expect(onSend).toHaveBeenCalledWith("review the diff", undefined);
    expect((input as HTMLInputElement).value).toBe("");
  });

  it("sends on Enter but inserts a newline on Shift+Enter", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: /message the agent/i });

    // Shift+Enter doesn't submit — it's a newline (the textarea's default).
    fireEvent.change(input, { target: { value: "line one" } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    // Plain Enter submits the trimmed text and clears the box.
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("line one", undefined);
    expect((input as HTMLTextAreaElement).value).toBe("");
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

  function pasteImage(input: HTMLElement) {
    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    fireEvent.paste(input, {
      clipboardData: { items: [{ kind: "file", type: "image/png", getAsFile: () => file }] },
    });
  }

  it("attaches a pasted image, sends it with the text, then clears", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: /message the agent/i });

    pasteImage(input);
    // FileReader.readAsDataURL is async — wait for the attachment chip.
    expect(await screen.findByRole("button", { name: /remove image/i })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "what is this" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, image] = onSend.mock.calls[0];
    expect(text).toBe("what is this");
    expect(image.media_type).toBe("image/png");
    expect(image.data.length).toBeGreaterThan(0); // raw base64, prefix stripped
    expect((input as HTMLInputElement).value).toBe("");
    expect(screen.queryByRole("button", { name: /remove image/i })).toBeNull();
  });

  it("sends an image-only message (no caption)", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: /message the agent/i });

    pasteImage(input);
    await screen.findByRole("button", { name: /remove image/i });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledTimes(1);
    expect(onSend.mock.calls[0][0]).toBe(""); // empty text
    expect(onSend.mock.calls[0][1].media_type).toBe("image/png");
  });

  it("attaches a dropped image, sends it with the text, then clears", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: /message the agent/i });

    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    fireEvent.drop(document.body, { dataTransfer: { files: [file], types: ["Files"] } });
    // FileReader.readAsDataURL is async — wait for the attachment chip.
    expect(await screen.findByRole("button", { name: /remove image/i })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "what is this" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, image] = onSend.mock.calls[0];
    expect(text).toBe("what is this");
    expect(image.media_type).toBe("image/png");
    expect(image.data.length).toBeGreaterThan(0); // raw base64, prefix stripped
    expect(screen.queryByRole("button", { name: /remove image/i })).toBeNull();
  });

  it("ignores a dropped non-image file", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(document.body, { dataTransfer: { files: [file], types: ["Files"] } });

    expect(screen.queryByRole("button", { name: /remove image/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows a window-wide overlay while dragging a file and clears on drop or leave", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const overlay = () => screen.queryByText(/drop an image to attach/i);

    // A file drag anywhere in the window shows the overlay.
    fireEvent.dragOver(document.body, { dataTransfer: { types: ["Files"] } });
    expect(overlay()).toBeInTheDocument();

    // Leaving the window (relatedTarget null) clears it.
    fireEvent.dragLeave(document.body, { relatedTarget: null });
    expect(overlay()).toBeNull();

    fireEvent.dragOver(document.body, { dataTransfer: { types: ["Files"] } });
    expect(overlay()).toBeInTheDocument();
    fireEvent.drop(document.body, { dataTransfer: { files: [], types: ["Files"] } });
    expect(overlay()).toBeNull();
  });

  it("does not show the overlay for a non-file drag", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);

    fireEvent.dragOver(document.body, { dataTransfer: { types: ["text/plain"] } });
    expect(screen.queryByText(/drop an image to attach/i)).toBeNull();
  });

  describe("busy toggle", () => {
    it("shows Stop (not Send) while busy and calls onStop when clicked", () => {
      const onSend = vi.fn();
      const onStop = vi.fn();
      render(<ChatInput onSend={onSend} busy onStop={onStop} />);

      expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: /stop the agent/i }));
      expect(onStop).toHaveBeenCalledTimes(1);
    });

    it("does not send on Enter while busy", () => {
      const onSend = vi.fn();
      render(<ChatInput onSend={onSend} busy onStop={vi.fn()} />);

      const input = screen.getByRole("textbox", { name: /message the agent/i });
      fireEvent.change(input, { target: { value: "queued thought" } });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onSend).not.toHaveBeenCalled();
    });

    it("shows Send (not Stop) when idle", () => {
      const onSend = vi.fn();
      render(<ChatInput onSend={onSend} />);

      expect(screen.getByRole("button", { name: /send/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /stop the agent/i })).toBeNull();
    });
  });
});
