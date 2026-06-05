// Minimal path routing — no router dependency. The home page lives at "/" and a
// review surface at "/s/<uuid>". Navigation is plain anchor hrefs (full loads);
// Vite's SPA fallback serves index.html for the deep route.

export type Route = { kind: "home" } | { kind: "surface"; surface: string };

export function routeFromPath(pathname: string): Route {
  const match = pathname.match(/^\/s\/(.+)$/);
  if (match) {
    return { kind: "surface", surface: decodeURIComponent(match[1]) };
  }
  return { kind: "home" };
}
