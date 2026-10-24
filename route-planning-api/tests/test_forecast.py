from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
import xarray as xr

from service.forecast import GridForecast
from service.providers import normalize, validate_request


def grid_file(tmp_path, gap=3, nan=False):
    times = np.array(['2026-10-24T00:00:00', f'2026-10-24T{gap:02d}:00:00'], dtype='datetime64[ns]')
    values = np.full((2, 2, 2), 2.0)
    values[1] = 4
    if nan:
        values[1, 0, 0] = np.nan
    ds = xr.Dataset({'wave': (['time', 'lat', 'lon'], values, {'units': 'm'}),
                     'wind': (['time', 'lat', 'lon'], np.ones((2, 2, 2)) * 10, {'units': 'm/s'})},
                    coords={'time': times, 'lat': [40, 42], 'lon': [-20, -18]})
    path = tmp_path / 'forecast.nc'
    ds.to_netcdf(path, engine='scipy')
    now = datetime(2026, 10, 24, tzinfo=UTC)
    meta = {'name': 'Test forecast', 'datasetId': 'test', 'retrievedAt': now, 'refreshAfter': now + timedelta(days=1)}
    return path, meta, now


def test_samples_location_future_time_and_units(tmp_path):
    path, meta, now = grid_file(tmp_path)
    forecast = GridForecast([(path, meta)], now)
    sample = forecast.sample(-19, 41, now + timedelta(hours=1.5))
    assert sample['wave'] == pytest.approx(3)
    assert sample['wind'] == pytest.approx(19.438444924)
    assert sample['u'] is None
    assert forecast.sample(-50, 41, now)['wave'] is None
    assert forecast.sample(-19, 41, now + timedelta(hours=4))['wave'] is None
    values, source_ids = forecast.sample_with_provenance(-19, 41, now + timedelta(hours=1.5))
    assert values == sample
    assert source_ids == {'wave': forecast.sources[0]['snapshotId'], 'wind': forecast.sources[0]['snapshotId']}
    assert forecast.sample_with_provenance(-50, 41, now)[1] == {}


def test_missing_timesteps_and_cells_are_not_filled_with_calm(tmp_path):
    path, meta, now = grid_file(tmp_path, gap=12)
    forecast = GridForecast([(path, meta)], now)
    assert forecast.sample(-19, 41, now + timedelta(hours=6))['wave'] is None
    path, meta, now = grid_file(tmp_path, nan=True)
    assert GridForecast([(path, meta)], now).sample(-19, 41, now + timedelta(hours=1))['wave'] is None


def test_expired_forecast_is_visible_but_not_used(tmp_path):
    path, meta, now = grid_file(tmp_path)
    meta['refreshAfter'] = now - timedelta(hours=1)
    forecast = GridForecast([(path, meta)], now)
    assert forecast.sources[0]['stale']
    assert forecast.sample(-19, 41, now)['wave'] is None


def test_regional_snapshots_use_newest_available_value_without_losing_other_regions(tmp_path):
    path, meta, now = grid_file(tmp_path)
    with xr.open_dataset(path) as raw:
        newer = raw.load().copy(deep=True)
    newer['wave'][:] = 8
    newer = newer.assign_coords(lon=[-19, -17])
    newer_path = tmp_path / 'newer.nc'
    newer.to_netcdf(newer_path, engine='scipy')
    newer_meta = dict(meta, retrievedAt=now + timedelta(minutes=1))
    forecast = GridForecast([(path, meta), (newer_path, newer_meta)], now)
    assert forecast.sample(-18.5, 41, now)['wave'] == 8
    assert forecast.sample(-19.5, 41, now)['wave'] == 2
    assert forecast.sample(-17.5, 41, now)['wave'] == 8
    assert forecast.sample(-16, 41, now)['wave'] is None
    assert forecast.sample_with_provenance(-18.5, 41, now)[1]['wave'] == forecast.sources[0]['snapshotId']
    assert forecast.sample_with_provenance(-19.5, 41, now)[1]['wave'] == forecast.sources[1]['snapshotId']


def test_download_budget_rejects_global_and_long_requests():
    with pytest.raises(ValueError):
        validate_request((-180, -80, 180, 80), 10)
    with pytest.raises(ValueError):
        validate_request((-7, 48, 5, 54), 30)


def test_current_normalization_does_not_add_total_and_components():
    shape = (3, 3, 3)
    ds = xr.Dataset({key: (['time', 'latitude', 'longitude'], np.full(shape, value), {'units': 'm s-1'})
                     for key, value in [('uo', 1), ('vo', 2), ('utotal', 9), ('vtotal', 10)]},
                    coords={'time': np.array(['2026-10-24T00', '2026-10-24T03', '2026-10-24T06'], dtype='datetime64[ns]'),
                            'latitude': [40, 41, 42], 'longitude': [-20, -19, -18]})
    result = normalize(ds, 'currents', (-20, 40, -18, 42))
    assert set(result.data_vars) == {'u', 'v'}
    assert float(result.u.mean()) == 1


def test_normalization_preserves_narrow_coastal_water_cells():
    values = np.full((2, 7, 7), np.nan)
    values[:, 2:5, 2:5] = 1.5
    ds = xr.Dataset({'VHM0': (['time', 'latitude', 'longitude'], values, {'units': 'm'})},
                    coords={'time': np.array(['2026-10-24T00', '2026-10-24T03'], dtype='datetime64[ns]'),
                            'latitude': 50 + np.arange(7) / 12,
                            'longitude': np.arange(7) / 12})
    result = normalize(ds, 'waves', (0, 50, 1, 51))
    assert result.sizes['lat'] == result.sizes['lon'] == 7
    assert int(np.isfinite(result.wave).sum()) == 18


def test_fine_regional_grid_precedes_newer_coarse_fallback(tmp_path):
    path, meta, now = grid_file(tmp_path)
    with xr.open_dataset(path) as raw:
        coarse = raw.load().copy(deep=True)
    coarse['wave'][:] = 8
    coarse_path = tmp_path / 'coarse.nc'
    coarse.to_netcdf(coarse_path, engine='scipy')
    detailed_meta = dict(meta, spatialResolutionDegrees=1 / 12)
    coarse_meta = dict(meta, spatialResolutionDegrees=.5, retrievedAt=now + timedelta(hours=1))
    forecast = GridForecast([(coarse_path, coarse_meta), (path, detailed_meta)], now)
    assert forecast.sample(-19, 41, now)['wave'] == 2


def test_global_longitude_wraps_but_regional_grid_does_not(tmp_path):
    path, meta, now = grid_file(tmp_path)
    with xr.open_dataset(path) as raw:
        regional = raw.load().copy(deep=True)
    global_grid = regional.isel(lon=[0, 1, 0, 1]).assign_coords(lon=[-180, -90, 0, 90])
    global_path = tmp_path / 'global.nc'
    global_grid.to_netcdf(global_path, engine='scipy')
    forecast = GridForecast([(global_path, meta)], now)
    assert forecast.sample(179.9, 41, now)['wave'] == 2
    assert forecast.sample(-180.1, 41, now)['wave'] == 2
    assert GridForecast([(path, meta)], now).sample(179.9, 41, now)['wave'] is None


def test_wave_grid_preserves_values_unknown_times_and_mercator_alignment(tmp_path):
    path, meta, now = grid_file(tmp_path)
    grid = GridForecast([(path, meta)], now).wave_grid((-20, 40, -18, 42), now)
    assert grid['projection'] == 'mercator' and grid['rowOrder'] == 'north_to_south'
    assert grid['frames'][0]['validAt'] == now.isoformat()
    assert len(grid['frames'][0]['values']) == grid['columns'] * grid['rows']
    assert set(grid['frames'][0]['values']) == {2}
    assert all(value is None for frame in grid['frames'][1:] for value in frame['values'])


def test_current_components_fall_back_as_one_vector_not_mixed_snapshots(tmp_path):
    path, meta, now = grid_file(tmp_path)
    entries = []
    for label, u, v, resolution in [('fine', 1, np.nan, .1), ('coarse', 2, 3, 1)]:
        with xr.open_dataset(path) as original:
            ds = original.load().drop_vars(['wave', 'wind'])
        shape = (2, 2, 2)
        ds['u'] = (['time', 'lat', 'lon'], np.full(shape, u), {'units': 'm/s'})
        ds['v'] = (['time', 'lat', 'lon'], np.full(shape, v), {'units': 'm/s'})
        target = tmp_path / (label + '.nc')
        ds.to_netcdf(target, engine='scipy')
        entries.append((target, dict(meta, _id=label, spatialResolutionDegrees=resolution)))
    values, sources = GridForecast(entries, now).sample_with_provenance(-19, 41, now)
    assert (values['u'], values['v']) == (2, 3)
    assert sources == {'u': 'coarse', 'v': 'coarse'}


def test_global_display_includes_distant_oceans_and_wraps_without_filling_unknowns(tmp_path):
    _, meta, now = grid_file(tmp_path)
    values = np.full((2, 2, 6), 5.0)
    values[1] = 7
    values[:, :, 3] = np.nan  # A genuine gap at Greenwich, not calm water.
    ds = xr.Dataset({'wave': (['time', 'lat', 'lon'], values, {'units': 'm'})},
                    coords={'time': np.array(['2026-10-24T00', '2026-10-24T06'], dtype='datetime64[ns]'),
                            'lat': [-60, 70], 'lon': [-180, -120, -60, 0, 60, 120]})
    path = tmp_path / 'global-display.nc'
    ds.to_netcdf(path, engine='scipy')
    grid = GridForecast([(path, meta)], now).wave_grid((-180, -80, 180, 80), now, columns=13, rows=9)
    assert grid['scope'] == 'global'
    first = np.array(grid['frames'][0]['values']).reshape(9, 13)
    # Both sides of the world, not a crop around any particular route.
    assert first[4, 2] == first[4, 10] == 5
    assert first[4, 0] == first[4, -1] == 5
    assert first[4, 6] is None
    assert all(value is None for value in first[0])
    assert all(value is None for value in first[-1])
    assert grid['frames'][1]['values'][4 * 13 + 2] == 7
    assert all(value is None for frame in grid['frames'][2:] for value in frame['values'])
