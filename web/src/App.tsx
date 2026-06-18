import { HomePage } from "./HomePage";
import { NewChatLanding } from "./NewChatLanding";
import { Surface } from "./Surface";
import { routeFromPath } from "./router";

export function App() {
  const route = routeFromPath(window.location.pathname);
  if (route.kind === "surface") return <Surface surface={route.surface} />;
  if (route.kind === "sessions") return <HomePage />;
  return <NewChatLanding />;
}
