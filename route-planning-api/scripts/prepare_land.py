"""Build an indexed, unsimplified GSHHG high-resolution screening mask.

The original licensed archive is retained. L1 treats inland waters as land;
only reviewed canal links may traverse them. Display geometry is separate.
"""
import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

import shapefile
from shapely import make_valid, to_wkb
from shapely.geometry import box, mapping, shape

ROOT = Path(__file__).resolve().parents[1]


def main():
    archive = ROOT / 'data/raw/gshhg-shp-2.3.7.zip'
    output = ROOT / 'data/geography'
    output.mkdir(parents=True, exist_ok=True)
    tiles, display = [], []
    with zipfile.ZipFile(archive) as z:
        for name in ['LICENSE.TXT', 'COPYING.LESSERv3']:
            (output / name).write_bytes(z.read(name))
        public_licenses = output / 'licenses'
        public_licenses.mkdir(parents=True, exist_ok=True)
        (public_licenses / 'GSHHG-LICENSE.txt').write_bytes(z.read('LICENSE.TXT'))
        (public_licenses / 'LGPL-3.0.txt').write_bytes(z.read('COPYING.LESSERv3'))
        prefix = 'GSHHS_shp/h/GSHHS_h_L1'
        reader = shapefile.Reader(**{ext: io.BytesIO(z.read(f'{prefix}.{ext}')) for ext in ['shp', 'shx', 'dbf']})
        for item in reader.iterShapes():
            polygon = make_valid(shape(item.__geo_interface__))
            if polygon.is_empty:
                continue
            w, s, e, n = polygon.bounds
            # Small islands remain untouched. Split continents to make repeated
            # intersection queries local without simplifying their coastlines.
            if e - w <= 5 and n - s <= 5:
                tiles.append(polygon)
            else:
                for lon in range(math.floor(w / 5) * 5, math.ceil(e / 5) * 5, 5):
                    for lat in range(math.floor(s / 5) * 5, math.ceil(n / 5) * 5, 5):
                        clipped = polygon.intersection(box(lon, lat, lon + 5, lat + 5))
                        if not clipped.is_empty:
                            tiles.append(clipped)
            # Display alone is reduced slightly; the screen always uses full h.
            if polygon.area > .0001:
                display.append({'type': 'Feature', 'properties': {},
                                'geometry': mapping(polygon.simplify(.001, preserve_topology=True))})
    path = output / 'gshhg-h.wkb.json'
    path.write_text(json.dumps([to_wkb(p, hex=True) for p in tiles], separators=(',', ':')))
    metadata = {'id': 'gshhg-2.3.7-h-L1', 'name': 'GSHHG 2.3.7 high resolution (L1)',
                'url': 'https://github.com/GenericMappingTools/gshhg-gmt/releases/tag/2.3.7',
                'license': 'LGPL-3.0-or-later', 'sourceSha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'polygons': len(tiles),
                'screeningSimplificationDegrees': 0, 'displaySimplificationDegrees': .001,
                'limitations': 'Older global shoreline data; not navigation charts, depth or clearance evidence.'}
    (output / 'manifest.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (output / 'land-detail.geojson').write_text(json.dumps(
        {'type': 'FeatureCollection', 'features': display}, separators=(',', ':')))
    print(json.dumps(metadata), flush=True)


if __name__ == '__main__':
    main()
