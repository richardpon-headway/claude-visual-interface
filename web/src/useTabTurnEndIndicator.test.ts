import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useTabTurnEndIndicator } from "./useTabTurnEndIndicator";

// The badge is asserted through the real favicon link the hook drives, so this
// exercises the hook + favicon integration together.
function badged(): boolean {
  const link = document.head.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) return false;
  return decodeURIComponent(link.href).includes("<circle");
}

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

afterEach(() => {
  document.head.querySelectorAll('link[rel="icon"]').forEach((l) => l.remove());
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
});

function render() {
  return renderHook(({ thinking }) => useTabTurnEndIndicator("s1", thinking), {
    initialProps: { thinking: false },
  });
}

describe("useTabTurnEndIndicator", () => {
  it("badges the tab when a turn ends (thinking true -> false)", () => {
    const { rerender } = render();
    rerender({ thinking: true }); // turn starts
    expect(badged()).toBe(false);
    rerender({ thinking: false }); // turn ends
    expect(badged()).toBe(true);
  });

  it("does not badge on an initial mid-turn snapshot (thinking already true)", () => {
    const { rerender } = renderHook(({ thinking }) => useTabTurnEndIndicator("s1", thinking), {
      initialProps: { thinking: true },
    });
    expect(badged()).toBe(false);
    rerender({ thinking: true }); // still streaming
    expect(badged()).toBe(false);
  });

  it("clears the badge when the tab becomes visible", () => {
    const { rerender } = render();
    rerender({ thinking: true });
    rerender({ thinking: false });
    expect(badged()).toBe(true);
    setVisibility("visible");
    expect(badged()).toBe(false);
  });

  it("clears a stale badge when a new turn starts", () => {
    const { rerender } = render();
    rerender({ thinking: true });
    rerender({ thinking: false });
    expect(badged()).toBe(true);
    rerender({ thinking: true }); // next turn begins
    expect(badged()).toBe(false);
  });

  it("clears the badge on unmount", () => {
    const { rerender, unmount } = render();
    rerender({ thinking: true });
    rerender({ thinking: false });
    expect(badged()).toBe(true);
    unmount();
    expect(badged()).toBe(false);
  });
});
