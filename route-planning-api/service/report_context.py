"""Small voyage briefs with read-only access to detailed route evidence."""
import json

READ_REPORT_TOOL = {'type': 'function', 'name': 'read_route_report',
    'description': 'Read any part of the complete original route report, including global wave grids. '
                   'Use JSON Pointer paths, e.g. /waveGrid, then its keys/array indices. Large containers are paged.',
    'parameters': {'type': 'object', 'properties': {
        'path': {'type': 'string', 'description': 'JSON Pointer path; empty string is report root.'},
        'offset': {'type': 'integer', 'minimum': 0},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}, 'required': ['path']}}


def direct_context(context):
    """Quick screening gets the facts it needs; large detail stays behind the tool."""
    report = context['routeReport']
    metadata = report.get('metadata', {})
    handoff = metadata.get('complianceHandoff', {})
    brief = {key: report[key] for key in ('schemaVersion', 'reportId', 'origin', 'destination',
        'departureTime', 'generatedAt', 'mode', 'assumptions', 'notices') if key in report}
    brief['metadata'] = {key: metadata[key] for key in ('ports', 'vesselModel', 'restrictionCatalog') if key in metadata}
    brief['metadata']['complianceHandoff'] = {key: handoff[key] for key in (
        'declaredContext', 'declarationStatus', 'declarationsUsedForRouting', 'interpretationRules') if key in handoff}
    brief['routes'] = []
    for index, route in enumerate(report['routes']):
        item = {key: route[key] for key in ('id', 'strategy', 'distanceNm', 'durationHours', 'eta',
            'speedKnots', 'forecastCoveragePercent', 'unknownWeatherHours', 'maxWaveHeightM', 'maxWindKnots',
            'roughSeaHours', 'passageIds', 'warnings', 'cost', 'emissions', 'canalTransits',
            'sailingHours', 'canalHours', 'waitingHours') if key in route}
        details = route.get('metadata', {})
        item['metadata'] = {key: details[key] for key in ('boundingBoxes', 'crossesAntimeridian',
            'coverage', 'passageEvents', 'restrictionEvents', 'restrictionScreening', 'qualityFlags') if key in details}
        item['details'] = {'availableThrough': 'read_route_report', 'path': f'/routes/{index}',
            'geometryPath': f'/routes/{index}/geometry', 'segmentsPath': f'/routes/{index}/segments',
            'segmentCount': len(route.get('segments', []))}
        brief['routes'].append(item)
    brief['detailAccess'] = {'availableThrough': 'read_route_report', 'path': '',
        'description': 'Complete original report retained. Geometry, timed segments, raw weather, source records '
                       'and global display arrays are not in this brief. Read only detail needed for your check. '
                       'Bounds and passage labels alone do not prove a jurisdiction or listed-area crossing.'}
    references = []
    for reference in context.get('documentReferences', []):
        text = reference.get('text', '')
        offset = context.get('cargoText', '').find(text) if text else -1
        references.append(({k: v for k, v in reference.items() if k != 'text'} |
                           {'cargoTextStart': offset, 'cargoTextEnd': offset + len(text)})
                          if offset >= 0 else reference)
    return context | {'routeReport': brief, 'documentReferences': references}


def read_report(report, path='', offset=0, limit=20):
    if not isinstance(path, str) or len(path) > 1000 or (path and not path.startswith('/')):
        return {'error': 'Use a JSON Pointer path.'}
    if not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 100:
        return {'error': 'offset must be nonnegative and limit between 1 and 100.'}
    value = report
    try:
        for part in path.split('/')[1:] if path else []:
            part = part.replace('~1', '/').replace('~0', '~')
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (KeyError, IndexError, ValueError, TypeError):
        return {'error': 'Path not found.'}
    def describe(child):
        if isinstance(child, list):
            return {'container': 'array', 'length': len(child)}
        if isinstance(child, dict):
            return {'container': 'object', 'keys': list(child)[:100], 'length': len(child)}
        return child
    if isinstance(value, dict):
        keys = list(value)[offset:offset + limit]
        result = {'path': path, 'length': len(value), 'values': {key: value[key] for key in keys}}
    elif isinstance(value, list):
        result = {'path': path, 'length': len(value), 'offset': offset,
                  'values': value[offset:offset + limit]}
    elif isinstance(value, str) and len(value) > 16000:
        return {'path': path, 'length': len(value), 'text': value[offset:offset + 16000],
                'nextOffset': offset + 16000 if offset + 16000 < len(value) else None}
    else:
        return {'path': path, 'value': value}
    result['nextOffset'] = offset + limit if offset + limit < len(value) else None
    if len(json.dumps(result)) > 20000:
        children = result['values']
        result['values'] = ({key: describe(child) for key, child in children.items()} if isinstance(children, dict)
                            else [describe(child) for child in children])
        result['expanded'] = False
        result['hint'] = 'Large containers are described. Select a deeper path or smaller limit for full values.'
    else:
        result['expanded'] = True
    return result
