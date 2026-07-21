import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BackgroundTasks } from "./BackgroundTasks";

describe("BackgroundTasks", () => {
  it("renders nothing when no task is running", () => {
    const { container } = render(<BackgroundTasks tasks={[]} onStop={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a single task with a description and a stop control", () => {
    const onStop = vi.fn();
    const { getByText } = render(
      <BackgroundTasks
        tasks={[{ task_id: "t1", description: "pnpm install" }]}
        onStop={onStop}
      />,
    );
    expect(getByText("pnpm install")).toBeTruthy();
    fireEvent.click(getByText("✕ stop"));
    expect(onStop).toHaveBeenCalledWith("t1");
  });

  it("collapses several tasks to a count with per-task and stop-all controls", () => {
    const onStop = vi.fn();
    const { getByText, getAllByText } = render(
      <BackgroundTasks
        tasks={[
          { task_id: "t1", description: "pnpm install" },
          { task_id: "t2", description: "snowflake query" },
        ]}
        onStop={onStop}
      />,
    );
    expect(getByText("2 background tasks")).toBeTruthy();

    // Stop all cancels every task; the per-row ✕ cancels just its own.
    fireEvent.click(getByText("stop all"));
    expect(onStop).toHaveBeenCalledWith("t1");
    expect(onStop).toHaveBeenCalledWith("t2");

    onStop.mockClear();
    fireEvent.click(getAllByText("✕")[1]);
    expect(onStop).toHaveBeenCalledTimes(1);
    expect(onStop).toHaveBeenCalledWith("t2");
  });
});
