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

function SessionRow({ session, onChanged }: { session: Session; onChanged: () => void }) {
  const repoBranch = [session.repo, session.branch].filter(Boolean).join(" · ");
  const archived = session.archived_at !== null;

  async function call(path: string, method: string) {
    await fetch(path, { method });
    onChanged();
  }

  // The title is the only link; actions sit beside it (not nested in the anchor).
  return (
    <div className="flex items-center gap-3 border-b border-zinc-800 px-4 py-3 hover:bg-zinc-900">
      <span className={`rounded px-1.5 py-0.5 text-xs ${statusClass(session.status)}`}>
        {session.status}
      </span>
      <a href={`/s/${encodeURIComponent(session.id)}`} className="flex-1 truncate hover:underline">
        {session.title ?? session.id}
      </a>
      <span className="text-xs text-zinc-500">
        {session.findings_total} findings · {session.findings_open} open
      </span>
      {repoBranch ? <span className="font-mono text-xs text-zinc-600">{repoBranch}</span> : null}
      <button
        type="button"
        className={actionButton}
        onClick={() =>
          call(`/sessions/${encodeURIComponent(session.id)}/${archived ? "unarchive" : "archive"}`, "POST")
        }
      >
        {archived ? "Unarchive" : "Archive"}
      </button>
      <button
        type="button"
        className={actionButton}
        onClick={() => call(`/sessions/${encodeURIComponent(session.id)}`, "DELETE")}
      >
        Delete
      </button>
    </div>
  );
}

export function HomePage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [query, setQuery] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(() => {
    const qs = includeArchived ? "?include_archived=true" : "";
    fetch(`/sessions${qs}`)
      .then((res) => (res.ok ? res.json() : { sessions: [] }))
      .then((data: { sessions?: Session[] }) => {
        setSessions(data.sessions ?? []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [includeArchived]);

  useEffect(() => {
    reload();
  }, [reload]);

  const visible = filterSessions(sessions, query);

  async function newChat() {
    const res = await fetch("/chats", { method: "POST" });
    if (!res.ok) {
      console.warn(`could not create chat: ${res.status}`);
      return;
    }
    const { session_id } = (await res.json()) as { session_id: string };
    window.location.href = `/s/${encodeURIComponent(session_id)}`;
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
        <label className="ml-auto flex items-center gap-1 text-xs text-zinc-400">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          show archived
        </label>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title…"
          className="rounded border border-zinc-800 bg-zinc-900 px-2 py-1 text-sm"
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
          visible.map((s) => <SessionRow key={s.id} session={s} onChanged={reload} />)
        )}
      </div>
    </div>
  );
}
