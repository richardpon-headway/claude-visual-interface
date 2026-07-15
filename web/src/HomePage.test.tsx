import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomePage } from "./HomePage";
import type { Session } from "./session";

const realLocation = window.location;

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.unstubAllGlobals();
});

function makeSession(overrides: Partial<Session>): Session {
  return {
    id: "id",
    type: "chat",
    title: null,
    status: "ready",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    deleted_at: null,
    starred_at: null,
    ...overrides,
  };
}

// Stubs fetch with a fixed session list for the mount-time GET /sessions, and
// records every call so tests can assert archive/delete requests.
function stubSessions(sessions: Session[]) {
  const fetchMock = vi.fn((url: string, init?: { method?: string }) => {
    if (url.startsWith("/sessions") && (!init || init.method === undefined)) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ sessions }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

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

  it("always fetches with archived included (no checkbox)", async () => {
    const fetchMock = stubSessions([]);
    render(<HomePage />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/sessions?include_archived=true"));
    expect(screen.queryByText(/show archived/i)).not.toBeInTheDocument();
  });
});

describe("HomePage — archive section", () => {
  it("shows Archive but not Delete on active rows", async () => {
    stubSessions([makeSession({ id: "a", title: "Active one" })]);
    render(<HomePage />);

    const row = (await screen.findByText("Active one")).closest("div") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("groups archived sessions into a collapsed section with a count, hidden until expanded", async () => {
    stubSessions([
      makeSession({ id: "a", title: "Active one" }),
      makeSession({ id: "b", title: "Archived one", archived_at: "2026-01-02T00:00:00Z" }),
    ]);
    render(<HomePage />);

    // Active row is visible; archived row is collapsed away.
    await screen.findByText("Active one");
    expect(screen.queryByText("Archived one")).not.toBeInTheDocument();

    // The section header carries the archived count.
    const header = screen.getByRole("button", { name: /archive \(1\)/i });
    expect(header).toHaveTextContent("1");

    // Expanding reveals the archived row with Unarchive + Delete.
    fireEvent.click(header);
    const archivedRow = (await screen.findByText("Archived one")).closest("div") as HTMLElement;
    expect(within(archivedRow).getByRole("button", { name: "Unarchive" })).toBeInTheDocument();
    expect(within(archivedRow).getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("hides the Archive section when there are no archived sessions", async () => {
    stubSessions([makeSession({ id: "a", title: "Active one" })]);
    render(<HomePage />);
    await screen.findByText("Active one");
    expect(screen.queryByRole("button", { name: /archive \(/i })).not.toBeInTheDocument();
  });
});

describe("HomePage — starred section", () => {
  it("clicking the star on an active row POSTs /star", async () => {
    const fetchMock = stubSessions([makeSession({ id: "a", title: "Active one" })]);
    render(<HomePage />);

    const row = (await screen.findByText("Active one")).closest("div") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Star" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/sessions/a/star", { method: "POST" }));
  });

  it("pins starred (non-archived) sessions into a Starred section, visible without expanding", async () => {
    stubSessions([
      makeSession({ id: "a", title: "Plain one" }),
      makeSession({ id: "b", title: "Pinned one", starred_at: "2026-01-02T00:00:00Z" }),
    ]);
    render(<HomePage />);

    // The starred row is visible immediately (the section is pinned open).
    await screen.findByText("Pinned one");
    expect(screen.getByText("Starred")).toBeInTheDocument();
    // Its toggle reads as already-starred (Unstar).
    const row = (screen.getByText("Pinned one").closest("div")) as HTMLElement;
    expect(within(row).getByRole("button", { name: "Unstar" })).toBeInTheDocument();
  });

  it("keeps an archived+starred session in Archive, not the Starred section", async () => {
    stubSessions([
      makeSession({ id: "a", title: "Active one" }),
      makeSession({
        id: "b",
        title: "Filed favorite",
        archived_at: "2026-01-02T00:00:00Z",
        starred_at: "2026-01-02T00:00:00Z",
      }),
    ]);
    render(<HomePage />);

    await screen.findByText("Active one");
    // Not surfaced in a Starred section, and hidden inside the collapsed Archive.
    expect(screen.queryByText("Starred")).not.toBeInTheDocument();
    expect(screen.queryByText("Filed favorite")).not.toBeInTheDocument();

    // It's in Archive; expanding reveals it, still bearing its star (Unstar toggle).
    fireEvent.click(screen.getByRole("button", { name: /archive \(1\)/i }));
    const row = (await screen.findByText("Filed favorite")).closest("div") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Unstar" })).toBeInTheDocument();
  });

  it("hides the Starred section when nothing is starred", async () => {
    stubSessions([makeSession({ id: "a", title: "Active one" })]);
    render(<HomePage />);
    await screen.findByText("Active one");
    expect(screen.queryByText("Starred")).not.toBeInTheDocument();
  });
});

describe("HomePage — delete confirmation", () => {
  it("does not delete until the confirmation is accepted", async () => {
    const fetchMock = stubSessions([
      makeSession({ id: "b", title: "Archived one", archived_at: "2026-01-02T00:00:00Z" }),
    ]);
    render(<HomePage />);

    fireEvent.click(await screen.findByRole("button", { name: /archive \(1\)/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    // Confirmation modal appears; nothing deleted yet.
    await screen.findByText(/delete session\?/i);
    expect(fetchMock).not.toHaveBeenCalledWith("/sessions/b", { method: "DELETE" });

    // Cancel closes it without deleting.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByText(/delete session\?/i)).not.toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalledWith("/sessions/b", { method: "DELETE" });
  });

  it("issues the DELETE request after confirming", async () => {
    const fetchMock = stubSessions([
      makeSession({ id: "b", title: "Archived one", archived_at: "2026-01-02T00:00:00Z" }),
    ]);
    render(<HomePage />);

    fireEvent.click(await screen.findByRole("button", { name: /archive \(1\)/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await screen.findByText(/delete session\?/i);

    // The modal's Delete confirms.
    const modal = screen.getByText(/delete session\?/i).closest("div") as HTMLElement;
    fireEvent.click(within(modal).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/sessions/b", { method: "DELETE" }),
    );
  });
});
