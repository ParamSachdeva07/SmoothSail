import hashlib
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr
from service.interpolation import GridField

KNOTS_PER_MS = 1.9438444924


def as_utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class GridForecast:
    """Load regional grids once; interpolate without database/network calls per point."""
    def __init__(self, entries: list[tuple[Path, dict]], now=None):
        self.fields = {}
        self.sources = []
        now = now or datetime.now(UTC)
        for path, metadata in sorted(entries, key=lambda entry: (
                entry[1].get('spatialResolutionDegrees', .08333), -as_utc(entry[1]['retrievedAt']).timestamp())):
            stale = as_utc(metadata['refreshAfter']) <= now
            snapshot_id = str(metadata.get('_id') or hashlib.sha256(
                f"{metadata.get('datasetId')}|{metadata.get('region')}|{metadata['retrievedAt']}|{metadata.get('sha256')}".encode()).hexdigest())
            note = {k: metadata[k] for k in ['name', 'datasetId', 'region', 'retrievedAt', 'validFrom', 'validUntil',
                                             'forecastRunAt', 'refreshAfter', 'sha256', 'bounds', 'variables', 'maxStepHours', 'kind',
                                             'spatialResolutionDegrees', 'coverageRole'] if k in metadata}
            note['snapshotId'] = snapshot_id
            note['interpolation'] = 'linear in latitude, longitude and valid time; no extrapolation or missing-cell fill'
            note['stale'] = stale
            self.sources.append(note)
            if stale:
                continue
            with xr.open_dataset(path) as original:
                ds = original.load()
            renames = {name: target for name, target in [('latitude', 'lat'), ('longitude', 'lon')]
                       if name in ds.coords}
            ds = ds.rename(renames)
            if not all(axis in ds.coords for axis in ['time', 'lat', 'lon']):
                raise ValueError('Forecast requires time, latitude and longitude coordinates.')
            ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby(['time', 'lat', 'lon'])
            ds = ds.drop_duplicates('lon')
            times = ds.time.values.astype('datetime64[s]').astype(float)
            if any(len(axis) < 2 or not np.all(np.diff(axis) > 0) for axis in (times, ds.lat.values, ds.lon.values)):
                raise ValueError('Forecast axes must contain at least two distinct, increasing coordinates.')
            for name in ['wave', 'wind', 'u', 'v']:
                if name not in ds:
                    continue
                array = ds[name]
                for dimension in list(array.dims):
                    if dimension not in ['time', 'lat', 'lon']:
                        if dimension == 'depth':
                            array = array.isel({dimension: int(abs(array[dimension]).argmin())})
                        elif array.sizes[dimension] == 1:
                            array = array.isel({dimension: 0})
                        else:
                            raise ValueError('Unexpected forecast dimension.')
                values = array.transpose('time', 'lat', 'lon').values
                units = str(array.attrs.get('units', '')).lower().replace(' ', '')
                if name in ['u', 'v'] and units not in ['m/s', 'ms-1', 'm.s-1']:
                    raise ValueError('Current vectors must use metres per second.')
                if name == 'wave' and units not in ['m', 'metres', 'meters']:
                    raise ValueError('Wave height must use metres.')
                if name == 'wind':
                    if units in ['m/s', 'ms-1', 'm.s-1']:
                        values = values * KNOTS_PER_MS
                    elif units not in ['knots', 'knot', 'kt']:
                        raise ValueError('Wind units are missing or unsupported.')
                axes = (times, ds.lat.values, ds.lon.values)
                # A regular global longitude grid is periodic, unlike regional
                # grids. Extend one genuine ocean column across the dateline.
                spacing = float(ds.lon[1] - ds.lon[0])
                if float(ds.lon[-1] - ds.lon[0]) + spacing >= 359.99:
                    longitudes = np.concatenate(([float(ds.lon[-1]) - 360], ds.lon.values,
                                                 [float(ds.lon[0]) + 360]))
                    values = np.concatenate((values[:, :, -1:], values, values[:, :, :1]), axis=2)
                    axes = (times, ds.lat.values, longitudes)
                self.fields.setdefault(name, []).append(GridField(axes, values,
                    float(metadata.get('maxStepHours', 6)) * 3600, snapshot_id))

    def sample(self, lon, lat, time):
        return self._sample(lon, lat, time, False)[0]

    def sample_with_provenance(self, lon, lat, time):
        return self._sample(lon, lat, time, True)

    def sample_weather(self, lon, lat, time):
        return self._sample(lon, lat, time, False, ('wave', 'wind'))[0]

    def _sample(self, lon, lat, time, include_provenance, variables=('wave', 'wind', 'u', 'v')):
        result = dict.fromkeys(['wave', 'wind', 'u', 'v'])
        source_ids = {}
        timestamp = time.timestamp()
        longitude = ((lon + 180) % 360) - 180
        for name, fields in self.fields.items():
            if name not in variables or name in ('u', 'v'):
                continue
            for field in fields:
                value = field.sample(timestamp, lat, longitude)
                if value is not None and (name in ['u', 'v'] or value >= 0):
                    result[name] = value
                    if include_provenance:
                        source_ids[name] = field.snapshot_id
                    break
        if 'u' in variables or 'v' in variables:
            north_fields = {field.snapshot_id: field for field in self.fields.get('v', [])}
            for east_field in self.fields.get('u', []):
                north_field = north_fields.get(east_field.snapshot_id)
                if north_field is None:
                    continue
                u = east_field.sample(timestamp, lat, longitude)
                v = north_field.sample(timestamp, lat, longitude)
                if u is not None and v is not None:
                    result.update(u=u, v=v)
                    if include_provenance:
                        source_ids.update(u=east_field.snapshot_id, v=east_field.snapshot_id)
                    break
        return result, source_ids

    def sample_many(self, name, longitudes, latitudes, timestamps):
        coordinates = np.column_stack((timestamps, latitudes, (np.asarray(longitudes) + 180) % 360 - 180))
        result = np.full(len(coordinates), np.nan)
        for field in self.fields.get(name, []):
            missing = np.flatnonzero(~np.isfinite(result))
            if not len(missing):
                break
            values = field.sample_many(coordinates[missing])
            if name not in ['u', 'v']:
                values[values < 0] = np.nan
            result[missing] = values
        return result

    def wave_grid(self, bounds, departure):
        if not self.fields.get('wave'):
            return None
        west, south, east, north = bounds
        columns, rows = 128, 64
        # Uniform Mercator rows keep the raster geographically aligned with map textures.
        mercator = lambda lat: math.asinh(math.tan(math.radians(lat)))
        latitudes = np.degrees(np.arctan(np.sinh(np.linspace(mercator(north), mercator(south), rows))))
        latitudes[0], latitudes[-1] = north, south
        lons, lats = np.meshgrid(np.linspace(west, east, columns), latitudes)
        frames = []
        for hours in range(0, 241, 6):
            valid_at = departure + timedelta(hours=hours)
            values = self.sample_many('wave', lons.ravel(), lats.ravel(),
                                      np.full(lons.size, valid_at.timestamp()))
            frames.append({'hour': hours, 'validAt': valid_at.isoformat(),
                           'values': [round(float(value), 2) if np.isfinite(value) else None for value in values]})
        return {'bounds': list(bounds), 'columns': columns, 'rows': rows, 'projection': 'mercator',
                'rowOrder': 'north_to_south', 'units': 'm', 'frames': frames,
                'interpretation': 'Interpolated forecast display; not additional observations or storm boundaries. Null is unknown.'}
