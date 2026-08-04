import { describe, expect, it } from "vitest";

import { BOTTOM_SLACK_PX, isNearBottom } from "./scroll";

describe("isNearBottom", () => {
  it("is true when pinned exactly at the bottom", () => {
    expect(isNearBottom({ scrollTop: 900, scrollHeight: 1000, clientHeight: 100 }, 40)).toBe(true);
  });

  it("is true within the slack window", () => {
    // 30px from the bottom, slack 40 → still counts as pinned.
    expect(isNearBottom({ scrollTop: 870, scrollHeight: 1000, clientHeight: 100 }, 40)).toBe(true);
  });

  it("is true at exactly the slack boundary", () => {
    expect(isNearBottom({ scrollTop: 860, scrollHeight: 1000, clientHeight: 100 }, 40)).toBe(true);
  });

  it("is false once scrolled up past the slack", () => {
    // 41px from the bottom, slack 40 → detached.
    expect(isNearBottom({ scrollTop: 859, scrollHeight: 1000, clientHeight: 100 }, 40)).toBe(false);
  });

  it("is true when content fits without scrolling", () => {
    expect(isNearBottom({ scrollTop: 0, scrollHeight: 100, clientHeight: 100 }, 40)).toBe(true);
  });

  it("exposes a sensible default slack", () => {
    expect(BOTTOM_SLACK_PX).toBe(40);
  });
});
