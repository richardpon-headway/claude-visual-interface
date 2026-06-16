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

  function getForm() {
    return screen.getByRole("textbox", { name: /message the agent/i }).closest("form")!;
  }

  it("attaches a dropped image, sends it with the text, then clears", async () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const input = screen.getByRole("textbox", { name: /message the agent/i });

    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    fireEvent.drop(getForm(), { dataTransfer: { files: [file] } });
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
    fireEvent.drop(getForm(), { dataTransfer: { files: [file] } });

    expect(screen.queryByRole("button", { name: /remove image/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("highlights the form while dragging and clears on drop or leave", () => {
    const onSend = vi.fn();
    render(<ChatInput onSend={onSend} />);
    const form = getForm();

    fireEvent.dragOver(form);
    expect(form.className).toContain("ring-zinc-500");

    fireEvent.dragLeave(form);
    expect(form.className).not.toContain("ring-zinc-500");

    fireEvent.dragOver(form);
    expect(form.className).toContain("ring-zinc-500");
    fireEvent.drop(form, { dataTransfer: { files: [] } });
    expect(form.className).not.toContain("ring-zinc-500");
  });
});
