// Runtime control of the browser-tab favicon. There is no static badged icon on
// disk; both the plain and badged variants are synthesized from the same base markup
// so the badge stays visually consistent with the shipped web/public/favicon.svg.

// Base icon markup, minus the closing tag so a badge can be appended before it.
// Mirrors web/public/favicon.svg (green rounded square + light sparkle).
const BASE_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">' +
  '<rect width="64" height="64" rx="13" fill="#12ab66"/>' +
  '<path fill="#eafaf2" d="M32 6 C34 22 42 30 58 32 C42 34 34 42 32 58 C30 42 22 34 6 32 C22 30 30 22 32 6 Z"/>';

// A red dot with a light ring, tucked into the top-right corner so it reads over both
// the green icon field and light/dark browser tab bars.
const BADGE = '<circle cx="49" cy="15" r="13" fill="#ffffff"/><circle cx="49" cy="15" r="9.5" fill="#f0503c"/>';

function dataUri(inner: string): string {
  return `data:image/svg+xml,${encodeURIComponent(`${inner}</svg>`)}`;
}

// Reuse the single <link rel="icon"> if present (index.html ships one), else create
// it. Idempotent: repeated calls mutate the same element rather than stacking links.
function iconLink(): HTMLLinkElement {
  let link = document.head.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    document.head.appendChild(link);
  }
  link.type = "image/svg+xml";
  return link;
}

// Show or hide the turn-end dot on the tab favicon.
export function setTurnEndFavicon(active: boolean): void {
  iconLink().href = dataUri(active ? BASE_ICON + BADGE : BASE_ICON);
}
