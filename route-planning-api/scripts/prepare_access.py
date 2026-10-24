"""Snap explicit offshore approach targets to the land-screened SeaRoute network.

These are planning approximations, not validated harbour pilotage coordinates.
Original port catalogue coordinates remain in Mongo for analytics.
"""
import argparse
import json
from pathlib import Path

import networkx as nx

from service.geo import distance_nm
from service.importing import ImportBundle
from service.navigation import connect_dateline, default_land_mask, exclude_unsupported_passages

TARGETS = {
    'NLRTM': [3.7, 51.95], 'USNYC': [-73.55, 40.25], 'PTLIS': [-9.7, 38.65],
    'CAHAL': [-63.1, 44.1], 'GBSOU': [-1.05, 50.6], 'FRLEH': [0.0, 49.45],
    'DEHAM': [7.9, 54.0], 'ESALG': [-5.35, 36.0], 'SGSIN': [103.8, 1.15],
    'CNSHA': [122.4, 30.8], 'JPTYO': [139.8, 34.9], 'AUSYD': [151.4, -33.9],
    'USLAX': [-118.3, 33.6], 'ZADUR': [31.15, -29.9], 'AEJEA': [54.95, 25.1],
    'INBOM': [72.65, 18.8],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=Path('data/raw'))
    parser.add_argument('--output', type=Path, default=Path('data/access_points.json'))
    args = parser.parse_args()
    bundle = ImportBundle().load(args.source_dir)
    graph = nx.Graph()
    for node in bundle.records['routing_nodes'].values():
        graph.add_node(node['nodeId'], coordinates=node['location']['coordinates'])
    for edge in bundle.records['routing_edges'].values():
        graph.add_edge(edge['from'], edge['to'], coordinates=edge['geometry']['coordinates'], passageIds=edge.get('passageIds', []))
    connect_dateline(graph)
    exclude_unsupported_passages(graph)
    excluded = default_land_mask().remove_crossings(graph)
    component = max(nx.connected_components(graph), key=len)
    result = {}
    for code, target in TARGETS.items():
        if code not in bundle.records['ports']:
            continue
        node = min(component, key=lambda n: distance_nm(target, bundle.records['routing_nodes'][n]['location']['coordinates']))
        point = bundle.records['routing_nodes'][node]['location']['coordinates']
        offset = distance_nm(point, target)
        if offset > 15:
            continue
        result[code] = {'nodeId': node, 'coordinates': point, 'method': 'offshore_target_snap',
                        'target': target, 'offsetNm': round(offset, 3)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'supportedPorts': len(result), 'landCrossingEdgesExcluded': excluded,
                       'mainComponentNodes': len(component), 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
