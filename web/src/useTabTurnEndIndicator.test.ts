import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useTabTurnEndIndicator } from "./useTabTurnEndIndicator";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

afterEach(() => {
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
});

function render(thinking = false) {
  return renderHook(({ thinking }) => useTabTurnEndIndicator("s1", thinking), {
    initialProps: { thinking },
  });
}

describe("useTabTurnEndIndicator", () => {
  it("flags unseen when a turn ends (thinking true -> false)", () => {
    const { result, rerender } = render(false);
    rerender({ thinking: true }); // turn starts
    expect(result.current).toBe(false);
    rerender({ thinking: false }); // turn ends
    expect(result.current).toBe(true);
  });

  it("does not flag on an initial mid-turn snapshot (thinking already true)", () => {
    const { result, rerender } = render(true);
    expect(result.current).toBe(false);
    rerender({ thinking: true }); // still streaming
    expect(result.current).toBe(false);
  });

  it("clears the flag when the tab becomes visible", () => {
    const { result, rerender } = render(true);
    rerender({ thinking: false });
    expect(result.current).toBe(true);
    setVisibility("visible");
    expect(result.current).toBe(false);
  });

  it("clears a stale flag when a new turn starts", () => {
    const { result, rerender } = render(true);
    rerender({ thinking: false });
    expect(result.current).toBe(true);
    rerender({ thinking: true }); // next turn begins
    expect(result.current).toBe(false);
  });
});
