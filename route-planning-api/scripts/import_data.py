import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.config import settings
from service.data import connect
from service.importing import ImportBundle, inventory


def main():
    parser = argparse.ArgumentParser(description='Inspect, validate and import maritime data into MongoDB.')
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--access-points', type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-rejected', action='store_true')
    parser.add_argument('--report', type=Path, default=Path('reports/import.json'))
    args = parser.parse_args()
    if not args.source_dir.is_dir():
        parser.error('Source directory does not exist.')
    try:
        if args.inspect:
            report = {'inventory': inventory(args.source_dir)}
        else:
            bundle = ImportBundle().load(args.source_dir, args.access_points)
            report = bundle.report()
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, default=str) + '\n')
            if args.apply:
                client, db = connect(settings)
                try:
                    report['applied'] = bundle.apply(db, args.allow_rejected, cache_dir=settings.data_dir / 'cache')
                finally:
                    client.close()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, default=str) + '\n')
        print(json.dumps({'report': str(args.report), 'counts': report.get('counts'),
                          'rejected': len(report.get('rejected', [])), 'applied': report.get('applied')}, indent=2))
        return 0
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    except Exception as error:
        print(f'Import failed ({type(error).__name__}). Check local configuration and file formats.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
