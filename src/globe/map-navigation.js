// Geographic positions stay canonical; presentation follows the visible world copy.
export function nearestWorldLongitude(longitude, center) {
  return longitude + 360 * Math.round((center - longitude) / 360);
}
export function shipZoomScale(zoom) {
  return Math.max(0.55, Math.min(2, 2 ** ((zoom - 3) * 0.3)));
}
export function latitudeWithinCoverage(latitude, bounds, zoom, height) {
  const y = lat => Math.asinh(Math.tan(lat * Math.PI / 180));
  const half = height / (512 * 2 ** zoom) * Math.PI;
  const bottom = y(bounds[0][1]) + half, top = y(bounds[1][1]) - half;
  const center = bottom > top ? (bottom + top) / 2 : Math.max(bottom, Math.min(top, y(latitude)));
  return Math.atan(Math.sinh(center)) * 180 / Math.PI;
}
