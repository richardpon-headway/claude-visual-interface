import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NewChatLanding } from "./NewChatLanding";

const realLocation = window.location;

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.unstubAllGlobals();
});

describe("NewChatLanding", () => {
  it("opens a chat and redirects into it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.startsWith("/chats/open")
          ? Promise.resolve({ ok: true, json: () => Promise.resolve({ session_id: "new-id" }) })
          : Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
      ),
    );
    // jsdom doesn't implement navigation; capture the replace() target instead.
    const loc = { replace: vi.fn() } as unknown as Location;
    Object.defineProperty(window, "location", { configurable: true, value: loc });

    render(<NewChatLanding />);

    await waitFor(() => expect(loc.replace).toHaveBeenCalledWith("/s/new-id"));
  });

  it("falls back to the session list when opening a chat fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.startsWith("/chats/open")
          ? Promise.reject(new Error("daemon down"))
          : // the HomePage fallback fetches /sessions on mount
            Promise.resolve({ ok: true, json: () => Promise.resolve({ sessions: [] }) }),
      ),
    );

    render(<NewChatLanding />);

    // HomePage renders its header once the open attempt fails.
    expect(await screen.findByText(/claude visual interface/i)).toBeInTheDocument();
  });
});
