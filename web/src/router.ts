// Minimal path routing — no router dependency. "/" is the launch landing (auto-opens
// a chat), the session list lives at "/sessions", and a chat surface at "/s/<uuid>".
// Navigation is plain anchor hrefs (full loads); Vite's SPA fallback serves index.html
// for the deep routes.

export type Route =
  | { kind: "home" }
  | { kind: "sessions" }
  | { kind: "surface"; surface: string };

export function routeFromPath(pathname: string): Route {
  const match = pathname.match(/^\/s\/(.+)$/);
  if (match) {
    return { kind: "surface", surface: decodeURIComponent(match[1]) };
  }
  if (pathname === "/sessions") {
    return { kind: "sessions" };
  }
  return { kind: "home" };
}
