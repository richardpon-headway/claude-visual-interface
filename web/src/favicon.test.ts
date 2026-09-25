import { afterEach, describe, expect, it } from "vitest";

import { setTurnEndFavicon } from "./favicon";

function iconLinks(): HTMLLinkElement[] {
  return Array.from(document.head.querySelectorAll<HTMLLinkElement>('link[rel="icon"]'));
}

afterEach(() => {
  iconLinks().forEach((l) => l.remove());
});

describe("setTurnEndFavicon", () => {
  it("shows a dotted svg data uri when active", () => {
    setTurnEndFavicon(true);
    const links = iconLinks();
    expect(links).toHaveLength(1);
    const href = decodeURIComponent(links[0].href);
    expect(href.startsWith("data:image/svg+xml,")).toBe(true);
    expect(href).toContain("<circle"); // dot overlay present
    expect(links[0].type).toBe("image/svg+xml");
  });

  it("restores the plain icon (no dot) when inactive, reusing one link element", () => {
    setTurnEndFavicon(true);
    setTurnEndFavicon(false);
    const links = iconLinks();
    expect(links).toHaveLength(1); // idempotent: mutates the single link, never stacks
    const href = decodeURIComponent(links[0].href);
    expect(href).toContain("#12ab66"); // base icon field
    expect(href).not.toContain("<circle");
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
