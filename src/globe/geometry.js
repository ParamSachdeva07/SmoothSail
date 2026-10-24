export function geometryLines(geometry) {
  if (geometry?.type === 'LineString' && Array.isArray(geometry.coordinates)) return [geometry.coordinates];
  if (geometry?.type === 'MultiLineString' && Array.isArray(geometry.coordinates)) return geometry.coordinates;
  return [];
}

// Preserve the API's antimeridian splits and every waypoint. Joining these
// components or smoothing their corners can draw a new path across land.
export function routeFeature(route) {
  return { type: 'Feature', properties: { id: route.id }, geometry: route.geometry };
}

export function routeBounds(geometry) {
  const points = geometryLines(geometry).flat();
  if (!points.length) return null;
  return points.reduce((bounds, [lon, lat]) => [
    [Math.min(bounds[0][0], lon), Math.min(bounds[0][1], lat)],
    [Math.max(bounds[1][0], lon), Math.max(bounds[1][1], lat)]
  ], [[Infinity, Infinity], [-Infinity, -Infinity]]);
}
