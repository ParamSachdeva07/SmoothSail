// Shared appearance, camera, interaction, and density controls.
// Dot radii are screen pixels; spacing values are nominal geographic degrees.

// Design values live in src/tokens.css. WebGL paint properties and camera
// calls cannot use var(), so these helpers read the same custom properties at
// runtime. Each takes the previous literal as a fallback, so if the
// stylesheet has not been applied (or this module is loaded under Node, as
// scripts/generate-dots.mjs does) the values are exactly what they were.
export function cssToken(name, fallback) {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function cssDurationMs(name, fallback) {
  const value = cssToken(name, '');
  if (value.endsWith('ms')) return Number.parseFloat(value);
  if (value.endsWith('s')) return Number.parseFloat(value) * 1000;
  return fallback;
}

export const SETTINGS = {
  dotColor: cssToken('--globe-dots', '#0cfd03'),
  backgroundColor: cssToken('--globe-sphere', '#0800ff'),
  screenBackgroundColor: cssToken('--bg', '#FAFAFA'),
  minZoom: 1,
  maxZoom: 6.5,
  initialZoom: 1.25,
  initialLongitude: 15,
  initialLatitude: 12,
  rotationSensitivity: 0.85,
  zoomSensitivity: 1,
  inertia: 0.92,
  autoRotate: true,
  autoRotateSpeed: 2,
  autoRotateResumeZoomTolerance: 0.02,
  levels: [
    // Larger dots use slightly wider grids; denser levels arrive earlier to preserve detail.
    { id: 'overview', radius: 1.30, spacing: 1.25, fade: [0.9, 1.0, 1.5, 2.05] },
    { id: 'global', radius: 1.28, spacing: 0.75, fade: [1.4, 2.05, 2.65, 3.25] },
    { id: 'regional', radius: 1.26, spacing: 0.47, fade: [2.55, 3.2, 3.8, 4.4] },
    { id: 'detailed', radius: 1.24, spacing: 0.31, fade: [3.7, 4.4, 5.0, 5.6] },
    { id: 'finest', radius: 1.22, spacing: 0.235, fade: [4.9, 5.6, 6.5, 7.0] }
  ],
  // Flat (equirectangular) levels for the 2D route map.
  //
  // These exist because the globe levels above deliberately widen longitude
  // spacing by 1 / cos(latitude) and stagger alternate rows — correct for a
  // sphere, where meridians converge, but wrong for plate carrée, where a
  // degree of longitude is a constant number of pixels at every latitude.
  // Reusing the globe grids flat makes high-latitude rows spread apart and
  // read as streaks. These use an equal lon/lat lattice and no stagger, so
  // spacing is uniform at every latitude and only zoom changes it.
  flatLevels: [
    { id: 'flat-coarse', radius: 1.35, spacing: 1.5 },
    { id: 'flat-fine', radius: 1.25, spacing: 0.75 }
  ]
};
