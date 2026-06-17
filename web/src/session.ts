// A session row from GET /sessions (mirrors the daemon session columns). Kept in
// sync with daemon/sessions.py.

export type Session = {
  id: string;
  type: string;
  title: string | null;
  status: string;
  repo: string | null;
  branch: string | null;
  worktree_path: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  deleted_at: string | null;
};

export function filterSessions(sessions: Session[], query: string): Session[] {
  const q = query.trim().toLowerCase();
  if (!q) return sessions;
  return sessions.filter((s) => (s.title ?? s.id).toLowerCase().includes(q));
}
