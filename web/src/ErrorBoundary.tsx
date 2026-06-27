import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

// A render/effect error in one subtree (e.g. a single artifact whose self-sizing
// hits a not-yet-parsed iframe) must not blank the whole conversation. This boundary
// catches it, logs once, and shows a compact inline fallback so the rest of the page
// keeps rendering. Class component because error boundaries have no hook equivalent.
export class ErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("render error caught by boundary", error, info);
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
