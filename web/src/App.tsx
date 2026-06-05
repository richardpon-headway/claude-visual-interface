import { HomePage } from "./HomePage";
import { ReviewSurface } from "./ReviewSurface";
import { routeFromPath } from "./router";

export function App() {
  const route = routeFromPath(window.location.pathname);
  return route.kind === "surface" ? <ReviewSurface surface={route.surface} /> : <HomePage />;
}
