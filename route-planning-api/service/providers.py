"""Bounded provider retrieval and normalized GridFS snapshots."""
import hashlib
import logging
import math
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import gridfs
import httpx
import numpy as np
import xarray as xr
from pymongo import ReplaceOne

from service.forecast import GridForecast, as_utc

REGIONS = {'north-atlantic': (-83, 25, 15, 62), 'channel': (-7, 48, 5, 54),
           'suez-approaches': (30, 27, 35, 33), 'panama-approaches': (-82, 6, -77, 12),
           'global-overview': (-180, -60, 179.9, 70)}
DATASETS = {
    'waves': 'cmems_mod_glo_wav_anfc_0.083deg_PT3H-i',
    'currents': 'cmems_mod_glo_phy_anfc_merged-uv_PT1H-i',
    'weather': 'ecmwf-ifs-0p25',
}
PORTWATCH = {
    'ports': 'https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Ports_Data/FeatureServer/0/query',
    'chokepoints': 'https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query',
}


def validate_request(bounds, days):
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -80 <= south < north <= 80):
        raise ValueError('Use a non-wrapping region within the supported latitude range.')
    if (east - west) * (north - south) > 5000 or not 1 <= days <= 10:
        raise ValueError('Request exceeds the regional area or ten-day download budget.')


def normalize(raw: xr.Dataset, kind, bounds, resolution=None, time_step_hours=3):
    ds = raw.rename({name: target for name, target in [('latitude', 'lat'), ('longitude', 'lon')] if name in raw.coords})
    if 'valid_time' in ds.coords:
        if 'step' in ds.dims:
            ds = ds.swap_dims({'step': 'valid_time'}).drop_vars('time', errors='ignore').rename({'valid_time': 'time'})
        elif 'time' not in ds.dims:
            ds = ds.rename({'valid_time': 'time'})
    if 'depth' in ds.dims:
        ds = ds.isel(depth=int(abs(ds.depth).argmin()))
    ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby(['time', 'lat', 'lon'])
    # Keeping a one-cell border supports interpolation at a request boundary.
    west, south, east, north = bounds
    ds = ds.sel(lon=slice(west - .5, east + .5), lat=slice(south - .5, north + .5))
    if resolution:
        # Explicit broad-ocean fallback. Native regional snapshots retain priority
        # and narrow passages never receive invented/interpolated land-cell data.
        ds = ds.isel(lon=slice(None, None, max(1, round(resolution / float(ds.lon[1] - ds.lon[0])))),
                     lat=slice(None, None, max(1, round(resolution / float(ds.lat[1] - ds.lat[0])))))
    if kind == 'waves':
        output = ds[['VHM0']].rename({'VHM0': 'wave'})
    elif kind == 'currents':
        # Use circulation components only. Do not add tidal/Stokes components to totals.
        output = ds[['uo', 'vo']].rename({'uo': 'u', 'vo': 'v'})
    else:
        u = next(name for name in ['u10', '10u'] if name in ds)
        v = next(name for name in ['v10', '10v'] if name in ds)
        output = xr.Dataset({'wind': np.hypot(ds[u], ds[v])})
        output.wind.attrs['units'] = 'm/s'
    if any(output.sizes.get(axis, 0) < 2 for axis in ['time', 'lat', 'lon']):
        raise ValueError('Provider subset has insufficient spatial or time coverage.')
    # Keep native spatial detail: striding past wet cells creates artificial
    # gaps in narrow coastal passages. The snapshot byte limit bounds storage.
    step_hours = float((output.time[1] - output.time[0]).values / np.timedelta64(1, 'h'))
    output = output.isel(time=slice(None, None, max(1, round(time_step_hours / step_hours))))
    return output.astype('float32').load()


def store_snapshot(db, path, metadata):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = hashlib.sha256((metadata['datasetId'] + metadata['region'] + digest).encode()).hexdigest()
    existing = db.forecast_cache.find_one({'_id': identity})
    if existing:
        # Re-downloading the same run must not reset forecast freshness.
        return existing
    metadata = dict(metadata, _id=identity, sha256=digest)
    GridForecast([(path, metadata)], now=as_utc(metadata['retrievedAt']))
    bucket = gridfs.GridFSBucket(db, bucket_name='forecast_files')
    with path.open('rb') as stream:
        file_id = bucket.upload_from_stream(path.name, stream, metadata={'sha256': digest})
    try:
        db.forecast_cache.insert_one(dict(metadata, gridFsFileId=file_id, status='ready'))
    except Exception:
        bucket.delete(file_id)
        raise
    return metadata


def refresh_forecast(settings, db, kind, bounds, departure, days=3, region='custom'):
    overview = region == 'global-overview'
    if overview:
        if tuple(bounds) != REGIONS['global-overview'] or not 1 <= days <= 10:
            raise ValueError('The global overview has a fixed area, half-degree spacing and ten-day budget.')
    else:
        validate_request(bounds, days)
    now = datetime.now(UTC)
    west, south, east, north = bounds
    dataset_id = DATASETS[kind]
    run_at = None
    with tempfile.TemporaryDirectory(prefix='tideline-forecast-') as temporary:
        directory = Path(temporary)
        if kind in ['waves', 'currents']:
            import copernicusmarine
            variables = ['VHM0'] if kind == 'waves' else ['uo', 'vo']
            start = departure.replace(hour=(departure.hour // 6) * 6, minute=0, second=0, microsecond=0)
            # Lazy access lets the explicit overview subsample before materializing
            # arrays. Never download a native-resolution global NetCDF file.
            with copernicusmarine.open_dataset(dataset_id=dataset_id, variables=variables,
                                   minimum_longitude=max(-180, west - .5), maximum_longitude=min(180, east + .5),
                                   minimum_latitude=south - .5, maximum_latitude=north + .5,
                                   start_datetime=start.isoformat(),
                                   end_datetime=(departure + timedelta(days=days)).isoformat(),
                                   username=settings.copernicus_username or None,
                                   password=settings.copernicus_password.get_secret_value() or None) as raw:
                ds = normalize(raw, kind, bounds, .5 if overview else None, 6 if overview else 3)
        else:
            from ecmwf.opendata import Client
            client = Client(source='ecmwf', model='ifs', resol='0p25')
            # Choose a completed long-horizon cycle, with a publication-lag allowance.
            eligible = now - timedelta(hours=8)
            run_at = eligible.replace(hour=12 if eligible.hour >= 12 else 0, minute=0, second=0, microsecond=0)
            first = max(0, math.floor((departure - run_at).total_seconds() / 3600 / 6) * 6)
            last = math.ceil(((departure - run_at).total_seconds() / 3600 + days * 24) / 6) * 6
            if last > 360:
                raise ValueError('Requested departure is beyond the selected ECMWF forecast.')
            path = directory / 'provider.grib2'
            client.retrieve(date=run_at.strftime('%Y%m%d'), time=run_at.hour, type='fc', stream='oper',
                            param=['10u', '10v'], step=list(range(first, last + 1, 6)), target=str(path))
            with xr.open_dataset(path, engine='cfgrib', backend_kwargs={'indexpath': ''}) as raw:
                ds = normalize(raw, kind, bounds, .5 if overview else None, 6 if overview else 3)
        target = directory / f'{kind}.nc'
        ds.to_netcdf(target, engine='h5netcdf', encoding={v: {'zlib': True, 'complevel': 3} for v in ds.data_vars})
        if target.stat().st_size > 128 * 1024**2:
            raise ValueError('Normalized regional snapshot exceeds the 128 MiB cache budget.')
        expiry = (run_at + timedelta(hours=24)) if run_at else (now + timedelta(hours=30))
        metadata = {'name': {'weather': 'ECMWF atmospheric forecast', 'waves': 'Copernicus wave forecast', 'currents': 'Copernicus circulation currents'}[kind],
                    'datasetId': dataset_id, 'region': region, 'kind': kind, 'retrievedAt': now,
                    'refreshAfter': expiry, 'bounds': {'west': float(ds.lon.min()), 'east': float(ds.lon.max()),
                                                     'south': float(ds.lat.min()), 'north': float(ds.lat.max())},
                    'validFrom': as_utc(str(ds.time.values[0])).isoformat(),
                    'validUntil': as_utc(str(ds.time.values[-1])).isoformat(),
                    'variables': list(ds.data_vars), 'maxStepHours': 6,
                    'spatialResolutionDegrees': .5 if overview else (.25 if kind == 'weather' else 1 / 12),
                    'coverageRole': 'broad_ocean_fallback' if overview else 'regional_detail',
                    'forecastRunAt': run_at.isoformat() if run_at else None}
        result = store_snapshot(db, target, metadata)
    db.source_status.update_one({'_id': kind}, {'$set': {'lastSuccess': now, 'datasetId': dataset_id}}, upsert=True)
    return {'source': kind, 'snapshot': str(result['_id'])}


def refresh_portwatch(db, days=30, mappings=None):
    # Retrieve only locations explicitly mapped from ports or selected passages.
    import re
    for locode, location_id in (mappings or {}).items():
        if not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}', locode) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', location_id):
            raise ValueError('Invalid PortWatch mapping file.')
        db.ports.update_one({'locode': locode}, {'$set': {'portwatchId': location_id}})
    ids = {str(p['portwatchId']) for p in db.ports.find({'portwatchId': {'$exists': True}}, {'portwatchId': 1})}
    passage_config = db.source_status.find_one({'_id': 'portwatch_locations'}) or {}
    ids_by_source = {'ports': ids, 'chokepoints': {str(x) for x in passage_config.get('locationIds', [])}}
    if not any(ids_by_source.values()):
        return {'source': 'portwatch', 'records': 0, 'note': 'Add reviewed portwatchId mappings before retrieval.'}
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) for values in ids_by_source.values() for value in values):
        raise ValueError('Invalid PortWatch location mapping.')
    since = (datetime.now(UTC) - timedelta(days=min(days, 90))).strftime('%Y-%m-%d')
    total = 0
    with httpx.Client(timeout=30) as client:
        for source, endpoint in PORTWATCH.items():
            if not ids_by_source[source]:
                continue
            encoded_ids = ','.join("'" + value + "'" for value in sorted(ids_by_source[source]))
            offset = 0
            while offset < 100000:
                response = client.get(endpoint, params={'f': 'json', 'where': f"portid IN ({encoded_ids}) AND date >= DATE '{since}'",
                                                        'outFields': '*', 'returnGeometry': 'false', 'resultRecordCount': 1000,
                                                        'resultOffset': offset, 'orderByFields': 'ObjectId ASC'})
                response.raise_for_status()
                data = response.json()
                if 'error' in data:
                    raise ValueError('PortWatch returned an API error.')
                records = []
                for feature in data.get('features', []):
                    attributes = feature['attributes']
                    observed = attributes['date']
                    if isinstance(observed, (int, float)):
                        observed = datetime.fromtimestamp(observed / 1000, UTC).date().isoformat()
                    record = {'source': source, 'locationId': str(attributes['portid']), 'date': str(observed)[:10],
                              'retrievedAt': datetime.now(UTC), 'observations': attributes}
                    key = {k: record[k] for k in ['source', 'locationId', 'date']}
                    records.append(ReplaceOne(key, record, upsert=True))
                if records:
                    db.port_activity.bulk_write(records, ordered=False)
                total += len(records)
                if not data.get('exceededTransferLimit'):
                    break
                if not records:
                    raise ValueError('PortWatch pagination returned an empty incomplete page.')
                offset += len(records)
            else:
                raise ValueError('PortWatch request exceeded its pagination budget.')
    return {'source': 'portwatch', 'records': total}


def refresh_for_bounds(settings, db, bounds, departure):
    try:
        validate_request(bounds, 10)
    except ValueError:
        # Large/dateline voyages still use cached coverage; never issue global
        # downloads or fail otherwise usable geography-only routing.
        logging.getLogger(__name__).info('Automatic retrieval skipped: route exceeds regional download bounds.')
        return
    now = datetime.now(UTC)
    for kind, dataset_id in DATASETS.items():
        query = {'datasetId': dataset_id, 'status': 'ready', 'refreshAfter': {'$gt': now},
                 'bounds.west': {'$lte': bounds[0]}, 'bounds.south': {'$lte': bounds[1]},
                 'bounds.east': {'$gte': bounds[2]}, 'bounds.north': {'$gte': bounds[3]}}
        if db.forecast_cache.find_one(query):
            continue
        try:
            refresh_forecast(settings, db, kind, bounds, departure, 10)
        except Exception:
            logging.getLogger(__name__).warning('Provider refresh failed for %s; credentials and raw errors are redacted.', kind)
            db.source_status.update_one({'_id': kind}, {'$set': {'lastFailure': now}}, upsert=True)


def refresh_overviews(settings, db):
    """One bounded refresh pass; called outside route calculation by the service."""
    now = datetime.now(UTC)
    for region in ['global-overview', 'channel', 'suez-approaches', 'panama-approaches']:
        for kind, dataset_id in DATASETS.items():
            # Regional wind comes from the global atmosphere snapshot; avoid
            # downloading the same global GRIB three more times per cycle.
            if kind == 'weather' and region != 'global-overview':
                continue
            if db.forecast_cache.find_one({'datasetId': dataset_id, 'region': region, 'status': 'ready',
                                           'refreshAfter': {'$gt': now + timedelta(hours=2)}}):
                continue
            try:
                refresh_forecast(settings, db, kind, REGIONS[region], now, 9, region)
            except Exception:
                logging.getLogger(__name__).warning('Bounded forecast refresh failed for %s/%s; using available coverage.', kind, region)
                db.source_status.update_one({'_id': kind}, {'$set': {'lastFailure': now}}, upsert=True)
    # Forecast files are replaceable caches. Bound storage to two successful
    # snapshots per dataset/region, preserving the previous run as a fallback.
    prune_snapshots(db, keep=2)


def prune_snapshots(db, keep=2):
    bucket = gridfs.GridFSBucket(db, bucket_name='forecast_files')
    counts, deleted = {}, 0
    for snapshot in db.forecast_cache.find({'status': 'ready'}).sort('retrievedAt', -1):
        key = snapshot['datasetId'], snapshot['region']
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > keep:
            db.forecast_cache.delete_one({'_id': snapshot['_id']})
            bucket.delete(snapshot['gridFsFileId'])
            deleted += 1
    return deleted
