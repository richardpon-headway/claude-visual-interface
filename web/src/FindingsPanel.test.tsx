import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FindingsPanel } from "./FindingsPanel";
import type { Finding } from "./viewState";

function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: "f1",
    session_id: "s",
    file: "a.py",
    anchor: { snippet: "x", range: { start: 3, end: 5 } },
    severity: "high",
    title: "Leaky thing",
    body: "b",
    suggested_patch: null,
    source_lens: null,
    actions: null,
    disposition: null,
    ...overrides,
  };
}

describe("FindingsPanel", () => {
  it("renders each finding as a button and fires onSelect on click", () => {
    const onSelect = vi.fn();
    const f = finding();
    render(<FindingsPanel findings={{ f1: f }} activeId={null} onSelect={onSelect} />);

    const row = screen.getByRole("button", { name: /Leaky thing/ });
    fireEvent.click(row);

    expect(onSelect).toHaveBeenCalledWith(f);
  });
});
