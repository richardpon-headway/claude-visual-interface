import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("renders children when they don't throw", () => {
    render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <p>ok</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("ok")).toBeInTheDocument();
    expect(screen.queryByText("fallback")).toBeNull();
  });

  it("shows the fallback when a child throws", () => {
    // React logs the caught error to console.error; silence it so test output stays clean.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback")).toBeInTheDocument();
    spy.mockRestore();
  });
});
