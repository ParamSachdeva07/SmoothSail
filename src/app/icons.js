// PLACEHOLDER ICONS.
//
// Intentionally temporary: plain 24×24 stroke glyphs, 1.5px stroke, no fill,
// no container, so they sit flat beside a label. They follow Lucide's grid and
// naming so that swapping to the real `lucide` package later is a rename, not
// a redesign — replace `icon()` with Lucide's `createElement(...)` and delete
// this file.

const PATHS = {
  // anchor-ish: departure port
  'map-pin': '<path d="M12 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11Z"/><circle cx="12" cy="10" r="2.5"/>',
  // arrival port
  flag: '<path d="M5 21V4"/><path d="M5 5h11l-2 3 2 3H5"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15"/><path d="M3.5 10h17"/><path d="M8 3v4M16 3v4"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M15.5 15.5 20 20"/>',
  'arrow-right': '<path d="M4 12h15"/><path d="M13 6l6 6-6 6"/>',
  'arrow-left': '<path d="M20 12H5"/><path d="M11 18l-6-6 6-6"/>',
  check: '<path d="M4 12.5 9.5 18 20 6"/>',
  'alert-triangle': '<path d="M12 4 22 20H2L12 4Z"/><path d="M12 10v5"/><path d="M12 17.5v.5"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8v.5"/>',
  ship: '<path d="M3 18s2-1 4.5-1 3 1 4.5 1 2-1 4.5-1 4.5 1 4.5 1"/><path d="M5 14 12 5l7 9"/><path d="M12 5V2"/>',
  layers: '<path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="M3 14l9 5 9-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>'
};

export function icon(name, size = 16) {
  const d = PATHS[name] ?? PATHS.info;
  return `<svg class="icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="1.5" stroke-linecap="square" stroke-linejoin="miter"
    aria-hidden="true" focusable="false">${d}</svg>`;
}
