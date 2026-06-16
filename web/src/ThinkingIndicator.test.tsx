import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThinkingIndicator } from "./ThinkingIndicator";

describe("ThinkingIndicator", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders nothing when inactive", () => {
    const { container } = render(<ThinkingIndicator active={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a word and an advancing elapsed counter when active", () => {
    const { container } = render(<ThinkingIndicator active={true} />);
    // Starts at 0s with a cycling word (ellipsis present).
    expect(container.textContent).toMatch(/…/);
    expect(container.textContent).toMatch(/\(0s\)/);

    // The elapsed counter advances as time passes.
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(container.textContent).toMatch(/\(3s\)/);
  });
});
