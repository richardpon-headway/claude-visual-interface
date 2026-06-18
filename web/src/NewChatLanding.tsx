import { useEffect, useState } from "react";

import { HomePage } from "./HomePage";

// The launch landing at "/": open a chat (the daemon reuses an empty "New chat" or
// creates one) and redirect into it, so opening CVI drops you straight into a chat.
// `replace` keeps Back from bouncing through this redirect. If the daemon is
// unreachable, fall back to the session list so the app is never stuck.
export function NewChatLanding() {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/chats/open", { method: "POST" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { session_id?: string } | null) => {
        if (cancelled) return;
        const id = data?.session_id;
        if (id) window.location.replace(`/s/${encodeURIComponent(id)}`);
        else setFailed(true);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) return <HomePage />;
  return <div className="p-4 text-sm text-zinc-500">starting…</div>;
}
