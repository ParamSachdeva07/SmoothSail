import math

from pyproj import Geod

GEOD = Geod(ellps='WGS84')


def distance_nm(a, b):
    return abs(GEOD.inv(*a, *b)[2]) / 1852


def bearing(a, b):
    return GEOD.inv(*a, *b)[0]


def interpolate(a, b, fraction):
    azimuth, _, metres = GEOD.inv(*a, *b)
    lon, lat, _ = GEOD.fwd(*a, azimuth, metres * fraction)
    return [lon, lat]


def densify(coords, max_nm=10):
    result = [list(coords[0])]
    for a, b in zip(coords, coords[1:]):
        count = max(1, math.ceil(distance_nm(a, b) / max_nm))
        result.extend(interpolate(a, b, i / count) for i in range(1, count))
        result.append(list(b))
    return result


def line_geometry(coords):
    """Split the display line at the dateline instead of drawing across the map."""
    parts = [[list(coords[0])]]
    for a, b in zip(coords, coords[1:]):
        if abs(b[0] - a[0]) > 180:
            adjusted = b[0] + (360 if b[0] < a[0] else -360)
            # +180 and -180 are the same meridian. Source networks may
            # represent it with two nodes joined by a zero-distance seam.
            if math.isclose(adjusted, a[0], abs_tol=1e-12):
                boundary, lat = a[0], b[1]
            else:
                boundary = 180 if adjusted > a[0] else -180
                fraction = (boundary - a[0]) / (adjusted - a[0])
                lat = a[1] + fraction * (b[1] - a[1])
            parts[-1].append([boundary, lat])
            parts.append([[-boundary, lat], list(b)])
        else:
            parts[-1].append(list(b))
    parts = [[point for index, point in enumerate(part) if index == 0 or point != part[index - 1]]
             for part in parts]
    parts = [part for part in parts if len(part) >= 2]
    if not parts:
        return {'type': 'LineString', 'coordinates': [list(coords[0]), list(coords[0])]}
    return {'type': 'LineString', 'coordinates': parts[0]} if len(parts) == 1 else {
        'type': 'MultiLineString', 'coordinates': parts}


def circle(lon, lat, radius_nm):
    ring = [list(GEOD.fwd(lon, lat, angle, radius_nm * 1852)[:2]) for angle in range(0, 361, 10)]
    return {'type': 'Polygon', 'coordinates': [ring]}
