import { describe, expect, it } from "vitest";

import { composeTitle } from "./title";

const WAVES = "\u{1F44B}\u{1F44B}\u{1F44B}";

describe("composeTitle", () => {
  it("prefixes the spinner frame while working", () => {
    expect(composeTitle("My session", "⠋", false)).toBe("⠋ My session");
  });

  it("prefixes the turn-end waves when idle but unseen", () => {
    expect(composeTitle("My session", null, true)).toBe(`${WAVES} My session`);
  });

  it("returns the plain base when idle and seen", () => {
    expect(composeTitle("My session", null, false)).toBe("My session");
  });

  it("lets the spinner win when a turn ended while a background task still runs", () => {
    // frame present AND wavesUnseen: working beats done, so no waves appear.
    const result = composeTitle("My session", "⠹", true);
    expect(result).toBe("⠹ My session");
    expect(result).not.toContain(WAVES);
  });
});
