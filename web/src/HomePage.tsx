import { useEffect, useState } from "react";

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

function SessionRow({ session }: { session: Session }) {
  const repoBranch = [session.repo, session.branch].filter(Boolean).join(" · ");
  return (
    <a
      href={`/s/${encodeURIComponent(session.id)}`}
      className="flex items-center gap-3 border-b border-zinc-800 px-4 py-3 hover:bg-zinc-900"
    >
      <span className={`rounded px-1.5 py-0.5 text-xs ${statusClass(session.status)}`}>
        {session.status}
      </span>
      <span className="flex-1 truncate">{session.title ?? session.id}</span>
      <span className="text-xs text-zinc-500">
        {session.findings_total} findings · {session.findings_open} open
      </span>
      {repoBranch ? <span className="font-mono text-xs text-zinc-600">{repoBranch}</span> : null}
    </a>
  );
}

export function HomePage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [query, setQuery] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/sessions")
      .then((res) => (res.ok ? res.json() : { sessions: [] }))
      .then((data: { sessions?: Session[] }) => {
        if (!cancelled) {
          setSessions(data.sessions ?? []);
          setLoaded(true);
        }
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const visible = filterSessions(sessions, query);

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col">
      <header className="flex items-center gap-3 px-4 py-3">
        <span className="font-semibold">Claude Visual Interface</span>
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
          visible.map((s) => <SessionRow key={s.id} session={s} />)
        )}
      </div>
    </div>
  );
}
