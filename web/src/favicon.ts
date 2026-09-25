// Runtime control of the browser-tab favicon. There is no static turn-end icon on
// disk; both the normal and waving variants are synthesized from the same base
// markup so they stay visually consistent with the shipped web/public/favicon.svg.

const GREEN_SQUARE = '<rect width="64" height="64" rx="13" fill="#12ab66"/>';
const SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">';

// Normal icon: green rounded square + light sparkle. Mirrors web/public/favicon.svg.
const BASE_ICON =
  SVG_OPEN +
  GREEN_SQUARE +
  '<path fill="#eafaf2" d="M32 6 C34 22 42 30 58 32 C42 34 34 42 32 58 C30 42 22 34 6 32 C22 30 30 22 32 6 Z"/>';

// Turn-end icon: a waving hand on the green square, so the tab clearly signals the
// agent finished (à la Eddy). The whole icon swaps rather than a subtle corner dot.
const WAVING_ICON =
  SVG_OPEN +
  GREEN_SQUARE +
  '<text x="32" y="34" font-size="40" text-anchor="middle" dominant-baseline="central">\u{1F44B}</text>';

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

// Swap the tab favicon to the waving hand (turn ended) or back to the normal icon.
export function setTurnEndFavicon(waving: boolean): void {
  iconLink().href = dataUri(waving ? WAVING_ICON : BASE_ICON);
}
