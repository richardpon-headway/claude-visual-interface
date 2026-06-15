import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomePage } from "./HomePage";

const realLocation = window.location;

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.unstubAllGlobals();
});

describe("HomePage — New chat", () => {
  it("creates a chat session and navigates to its surface", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/chats")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ session_id: "new-id" }) });
      }
      // the mount-time GET /sessions
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ sessions: [] }) });
    });
    vi.stubGlobal("fetch", fetchMock);

    // jsdom doesn't implement navigation; capture href assignment instead.
    const loc = { href: "" } as Location;
    Object.defineProperty(window, "location", { configurable: true, value: loc });

    render(<HomePage />);
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));

    await waitFor(() => expect(window.location.href).toBe("/s/new-id"));
    expect(fetchMock).toHaveBeenCalledWith("/chats", { method: "POST" });
  });
});
