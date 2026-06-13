import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ArtifactPane } from "./ArtifactPane";

describe("ArtifactPane", () => {
  it("renders the html in a no-script sandboxed iframe", () => {
    render(<ArtifactPane artifact={{ html: "<p>hi</p>", title: "design" }} />);
    const frame = screen.getByTitle("design") as HTMLIFrameElement;
    // Empty sandbox = the security boundary: no scripts, no network.
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("srcdoc")).toBe("<p>hi</p>");
  });

  it("falls back to a default title when none is given", () => {
    render(<ArtifactPane artifact={{ html: "<p>hi</p>", title: null }} />);
    expect(screen.getByTitle("artifact")).toBeInTheDocument();
  });
});
