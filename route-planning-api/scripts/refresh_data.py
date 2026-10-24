import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.config import settings
from service.data import connect, ensure_indexes
from service.providers import REGIONS, prune_snapshots, refresh_forecast, refresh_portwatch, validate_request


def main():
    parser = argparse.ArgumentParser(description='Preview or run bounded forecast/activity refreshes.')
    parser.add_argument('--region', choices=list(REGIONS), default='channel')
    parser.add_argument('--days', type=int, default=3)
    parser.add_argument('--sources', default='weather,waves,currents,portwatch')
    parser.add_argument('--execute', action='store_true', help='Download provider data and write Mongo. Otherwise only show request bounds.')
    parser.add_argument('--prune', action='store_true', help='Keep the newest two snapshots per dataset/region after a successful refresh.')
    args = parser.parse_args()
    sources = args.sources.split(',')
    if any(source not in ['weather', 'waves', 'currents', 'portwatch'] for source in sources):
        parser.error('Unknown source.')
    bounds = REGIONS[args.region]
    if args.region != 'global-overview':
        validate_request(bounds, args.days)
    elif not 1 <= args.days <= 10:
        parser.error('Global overview supports one to ten days.')
    if not args.execute:
        print(json.dumps({'region': args.region, 'bounds': bounds, 'days': args.days, 'sources': sources,
                          'note': 'Preview only. Add --execute to download and cache. ECMWF downloads selected global fields before cropping.'}, indent=2))
        return 0
    client = None
    try:
        client, db = connect(settings)
        ensure_indexes(db)
        for source in sources:
            if source == 'portwatch':
                mapping_file = settings.data_dir / 'portwatch_mappings.json'
                mappings = json.loads(mapping_file.read_text()) if mapping_file.exists() else None
                result = refresh_portwatch(db, mappings=mappings)
            else:
                result = refresh_forecast(settings, db, source, bounds, datetime.now(UTC), args.days, args.region)
            print(json.dumps(result))
        if args.prune:
            print(json.dumps({'removedSnapshots': prune_snapshots(db)}))
        return 0
    except Exception as error:
        print(f'Refresh failed ({type(error).__name__}). Check provider credentials, installed extras and requested coverage.', file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
