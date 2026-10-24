"""Prepare a display-only coast mask from the existing GSHHG display GeoJSON.

Usage: python scripts/build-land-mask.py /path/to/land-detail.geojson
Requires shapely. The routing service's original land mask is not modified.
"""
import json
import sys
from pathlib import Path

from shapely.geometry import mapping, shape

root = Path(__file__).resolve().parents[1]
source = json.loads(Path(sys.argv[1]).read_text())

def rounded(value):
    if isinstance(value, (list, tuple)):
        return [rounded(item) for item in value]
    return round(value, 4) if isinstance(value, float) else value

features = []
for feature in source['features']:
    geometry = mapping(shape(feature['geometry']).simplify(0.005, preserve_topology=True))
    geometry['coordinates'] = rounded(geometry['coordinates'])
    features.append({'type': 'Feature', 'properties': {}, 'geometry': geometry})

target = root / 'public/data/land-mask.geojson'
target.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':')))
print(f'{len(features)} polygons, {target.stat().st_size / 1_000_000:.2f} MB')
