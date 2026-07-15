import { useCallback, useEffect, useState } from "react";

import { filterSessions } from "./session";
import type { Session } from "./session";

function statusClass(status: string): string {
  switch (status) {
    case "running":
      return "bg-blue-900 text-blue-200";
    case "ready":
      return "bg-emerald-900 text-emerald-200";
    case "worked":
      return "bg-zinc-700 text-zinc-200";
    case "error":
      return "bg-red-900 text-red-200";
    default:
      return "bg-zinc-800 text-zinc-300";
  }
}

const actionButton = "rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-300 hover:bg-zinc-800";

function SessionRow({
  session,
  onChanged,
  onRequestDelete,
}: {
  session: Session;
  onChanged: () => void;
  onRequestDelete?: (session: Session) => void;
}) {
  const archived = session.archived_at !== null;
  const starred = session.starred_at !== null;

  async function call(path: string, method: string) {
    await fetch(path, { method });
    onChanged();
  }

  // Archived rows read as "set aside": a neutral status badge and a muted title.
  const badgeClass = archived ? "bg-zinc-800 text-zinc-400" : statusClass(session.status);
  const titleClass = archived ? "flex-1 truncate text-zinc-400 hover:underline" : "flex-1 truncate hover:underline";

  // The title is the only link; actions sit beside it (not nested in the anchor).
  return (
    <div className="flex items-center gap-3 border-b border-zinc-800 px-4 py-3 hover:bg-zinc-900">
      <span className={`rounded px-1.5 py-0.5 text-xs ${badgeClass}`}>{session.status}</span>
      <a href={`/s/${encodeURIComponent(session.id)}`} className={titleClass}>
        {session.title ?? session.id}
      </a>
      <button
        type="button"
        aria-label={starred ? "Unstar" : "Star"}
        title={starred ? "Unstar" : "Star"}
        className={`rounded px-1 text-base leading-none ${starred ? "text-amber-400 hover:text-amber-300" : "text-zinc-600 hover:text-zinc-300"}`}
        onClick={() => call(`/sessions/${encodeURIComponent(session.id)}/${starred ? "unstar" : "star"}`, "POST")}
      >
        {starred ? "★" : "☆"}
      </button>
      <button
        type="button"
        className={actionButton}
        onClick={() =>
          call(`/sessions/${encodeURIComponent(session.id)}/${archived ? "unarchive" : "archive"}`, "POST")
        }
      >
        {archived ? "Unarchive" : "Archive"}
      </button>
      {archived && onRequestDelete ? (
        <button type="button" className={actionButton} onClick={() => onRequestDelete(session)}>
          Delete
        </button>
      ) : null}
    </div>
  );
}

function DeleteConfirm({
  session,
  onCancel,
  onConfirm,
}: {
  session: Session;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  // Scrim closes; the card stops propagation so clicks inside don't cancel.
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onCancel}>
      <div
        className="w-full max-w-sm rounded-lg border border-zinc-700 bg-zinc-900 p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-sm font-semibold text-zinc-100">Delete session?</h2>
        <p className="mt-2 text-sm text-zinc-400">
          <span className="text-zinc-100">{session.title ?? session.id}</span> will be permanently
          deleted. This can’t be undone.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" className={actionButton} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="rounded border border-red-800 bg-red-900 px-2 py-0.5 text-xs text-red-100 hover:bg-red-800"
            onClick={onConfirm}
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}

export function HomePage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [query, setQuery] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Session | null>(null);

  const reload = useCallback(() => {
    fetch("/sessions?include_archived=true")
      .then((res) => (res.ok ? res.json() : { sessions: [] }))
      .then((data: { sessions?: Session[] }) => {
        setSessions(data.sessions ?? []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const visible = filterSessions(sessions, query);
  // Three bands: starred (non-archived) pins to the top, then active, then archive.
  // An archived+starred session stays in Archive but keeps its star icon.
  const starred = visible.filter((s) => s.starred_at !== null && s.archived_at === null);
  const active = visible.filter((s) => s.starred_at === null && s.archived_at === null);
  const archived = visible.filter((s) => s.archived_at !== null);

  async function newChat() {
    const res = await fetch("/chats", { method: "POST" });
    if (!res.ok) {
      console.warn(`could not create chat: ${res.status}`);
      return;
    }
    const { session_id } = (await res.json()) as { session_id: string };
    window.location.href = `/s/${encodeURIComponent(session_id)}`;
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    await fetch(`/sessions/${encodeURIComponent(pendingDelete.id)}`, { method: "DELETE" });
    setPendingDelete(null);
    reload();
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <header className="flex items-center gap-3 px-4 py-3">
        <span className="font-semibold">Claude Visual Interface</span>
        <button
          type="button"
          onClick={newChat}
          className="rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-200 hover:bg-zinc-800"
        >
          New chat
        </button>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title…"
          className="ml-auto rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-sm"
        />
      </header>
      <div className="min-h-0 flex-1 overflow-auto">
        {!loaded ? (
          <div className="p-4 text-sm text-zinc-500">loading…</div>
        ) : visible.length === 0 ? (
          <div className="p-4 text-sm text-zinc-500">
            {sessions.length === 0 ? "no sessions yet" : "no matches"}
          </div>
        ) : (
          <>
            {starred.length > 0 ? (
              <section>
                <div className="flex w-full items-center gap-2 border-b border-zinc-800 bg-zinc-950 px-4 py-3">
                  <span className="w-3 text-sm text-amber-400">★</span>
                  <span className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Starred
                  </span>
                  <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-500">
                    {starred.length}
                  </span>
                </div>
                {starred.map((s) => (
                  <SessionRow key={s.id} session={s} onChanged={reload} />
                ))}
              </section>
            ) : null}
            {active.length === 0 ? (
              <div className="p-4 text-sm text-zinc-500">no active sessions</div>
            ) : (
              active.map((s) => <SessionRow key={s.id} session={s} onChanged={reload} />)
            )}
            {archived.length > 0 ? (
              <section>
                <button
                  type="button"
                  aria-label={`Archive (${archived.length})`}
                  aria-expanded={archiveOpen}
                  onClick={() => setArchiveOpen((open) => !open)}
                  className="flex w-full items-center gap-2 border-b border-zinc-800 bg-zinc-950 px-4 py-3 text-left hover:bg-zinc-900"
                >
                  <span className="w-3 text-xs text-zinc-500">{archiveOpen ? "▼" : "▶"}</span>
                  <span className="text-xs font-semibold uppercase tracking-wide text-zinc-400">
                    Archive
                  </span>
                  <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-500">
                    {archived.length}
                  </span>
                </button>
                {archiveOpen
                  ? archived.map((s) => (
                      <SessionRow
                        key={s.id}
                        session={s}
                        onChanged={reload}
                        onRequestDelete={setPendingDelete}
                      />
                    ))
                  : null}
              </section>
            ) : null}
          </>
        )}
      </div>
      {pendingDelete ? (
        <DeleteConfirm
          session={pendingDelete}
          onCancel={() => setPendingDelete(null)}
          onConfirm={confirmDelete}
        />
      ) : null}
    </div>
  );
}
