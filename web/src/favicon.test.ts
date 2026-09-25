import { afterEach, describe, expect, it } from "vitest";

import { setTurnEndFavicon } from "./favicon";

const WAVE = "\u{1F44B}";

function iconLinks(): HTMLLinkElement[] {
  return Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[rel="icon"]'));
}

afterEach(() => {
  iconLinks().forEach((l) => l.remove());
});

describe("setTurnEndFavicon", () => {
  it("shows a waving-hand svg data uri when waving", () => {
    setTurnEndFavicon(true);
    const links = iconLinks();
    expect(links).toHaveLength(1);
    const href = decodeURIComponent(links[0].href);
    expect(href.startsWith("data:image/svg+xml,")).toBe(true);
    expect(href).toContain(WAVE); // waving hand present
    expect(links[0].type).toBe("image/svg+xml");
  });

  it("restores the normal icon (no wave) when inactive, reusing one link element", () => {
    setTurnEndFavicon(true);
    setTurnEndFavicon(false);
    const links = iconLinks();
    expect(links).toHaveLength(1); // idempotent: mutates the single link, never stacks
    const href = decodeURIComponent(links[0].href);
    expect(href).toContain("#eafaf2"); // base icon sparkle
    expect(href).not.toContain(WAVE);
  });

  it("reuses an existing link[rel=icon] rather than creating a second", () => {
    const existing = document.createElement("link");
    existing.rel = "icon";
    existing.href = "/favicon.svg";
    document.head.appendChild(existing);

    setTurnEndFavicon(true);

    const links = iconLinks();
    expect(links).toHaveLength(1);
    expect(links[0]).toBe(existing);
  });
});
