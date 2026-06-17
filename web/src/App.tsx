import { HomePage } from "./HomePage";
import { Surface } from "./Surface";
import { routeFromPath } from "./router";

export function App() {
  const route = routeFromPath(window.location.pathname);
  return route.kind === "surface" ? <Surface surface={route.surface} /> : <HomePage />;
}
