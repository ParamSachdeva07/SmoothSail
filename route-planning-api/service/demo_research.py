"""Bundled port research for one presentation voyage (FRLEH → SGSIN).

A fixed fixture, not a live assessment: findings cite the uploaded manifest and
official public sources. Route planning and rerouting still use the real service.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256

DEMO_PAIR = ('FRLEH', 'SGSIN')

# Official public pages the bundled findings cite (checked October 2026). Passages summarise the cited rule.
SOURCES = {
    'eu-ets-shipping': ('European Commission · Reducing emissions from the shipping sector',
        'https://climate.ec.europa.eu/areas-action/transport-decarbonisation/reducing-emissions-shipping-sector_en',
        'Since January 2024 the EU ETS covers emissions from ships of 5,000 GT and above calling at EU ports: 100% of emissions '
        'between EU ports and at berth, and 50% of emissions on voyages starting or ending outside the EU. Companies surrender '
        'allowances for 70% of 2025 emissions in 2026 and for 100% of reported emissions from 2027 onwards.'),
    'eu-ets-faq': ('European Commission · FAQ on maritime transport in the EU ETS',
        'https://climate.ec.europa.eu/areas-action/transport-decarbonisation/reducing-emissions-shipping-sector/faq-maritime-transport-eu-emissions-trading-system-ets_en',
        'Phase-in of surrender obligations: 40% (2024 emissions), 70% (2025) and 100% from 2026 emissions; methane and nitrous '
        'oxide are included from 2026. Allowances are surrendered by 30 September of the following year.'),
    'fueleu': ('EUR-Lex · Regulation (EU) 2023/1805 (FuelEU Maritime)', 'https://eur-lex.europa.eu/eli/reg/2023/1805/oj',
        'From 1 January 2025 the yearly average GHG intensity of energy used on board must be 2% below the 91.16 gCO2e/MJ '
        'reference (89.34 gCO2e/MJ). It applies to 50% of energy used on voyages into or out of the EU.'),
    'med-eca': ('IMO · New sulphur emission limits in the Mediterranean',
        'https://www.imo.org/en/mediacentre/pages/whatsnew-2254.aspx',
        'The Mediterranean Sea became an Emission Control Area for SOx and particulate matter under MARPOL Annex VI on '
        '1 May 2025; fuel oil sulphur content is limited to 0.10% m/m.'),
    'eu-customs-export': ('European Commission · Customs procedures for import and export',
        'https://taxation-customs.ec.europa.eu/customs-4/customs-procedures-import-and-export_en',
        'Goods leaving the EU customs territory are placed under the export procedure by lodging an export declaration; '
        'exit is confirmed at the customs office of exit.'),
    'wco-hs': ('World Customs Organization · HS Nomenclature 2022',
        'https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition.aspx',
        'The Harmonized System classifies traded goods; heading 85.07 covers electric accumulators, with 8507.60 for lithium-ion.'),
    'sg-customs-import': ('Singapore Customs · Import operations overview',
        'https://www.customs.gov.sg/doing-business/import-operations/import-operations-overview/',
        'Importers must obtain a customs import permit through TradeNet before goods are imported, and check whether the goods '
        'are controlled by a Competent Authority.'),
    'sg-duties': ('Singapore Customs · Duties and dutiable goods overview',
        'https://www.customs.gov.sg/doing-business/valuation-duties-and-fees/duties-and-dutiable-goods/duties-and-dutiable-goods-overview/',
        'Customs and excise duties apply only to intoxicating liquors, tobacco products, motor vehicles and petroleum products; '
        'GST (9%) is payable on imports on the CIF value plus any duty.'),
    'imo-number': ('IMO · Ship identification number scheme',
        'https://www.imo.org/en/OurWork/MSAS/Pages/IMO-identification-number-scheme.aspx',
        'The IMO number is a permanent unique ship identifier, mandatory for applicable ships under SOLAS regulation XI-1/3.'),
    'un-list': ('UN Security Council · Consolidated sanctions list',
        'https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list',
        'Consolidated list of individuals and entities subject to UN Security Council sanctions measures.'),
    'ofac-search': ('US Treasury OFAC · Sanctions List Search', 'https://sanctionssearch.ofac.treas.gov/',
        'Searchable US sanctions lists, including the SDN List, which identifies designated vessels by IMO number.'),
    'eu-sanctions-map': ('EU Sanctions Map', 'https://www.sanctionsmap.eu/',
        'Official overview of EU restrictive measures in force, including designated persons, entities and vessels.'),
    'jwc': ('Lloyd’s Market Association · Joint War Committee', 'https://lmalloyds.com/committee/joint-war-committee/',
        'The JWC Listed Areas of enhanced risk for hull war, strikes, terrorism and related perils include the Red Sea and '
        'the Gulf of Aden. Transits of listed areas require notice to war-risk underwriters and an additional premium.'),
    'ukmto': ('UKMTO · Voluntary Reporting Scheme', 'https://www.ukmto.org/',
        'UKMTO operates a Voluntary Reporting Scheme for merchant ships in the Voluntary Reporting Area covering the Red Sea, '
        'Gulf of Aden and wider Indian Ocean (UKHO chart Q6099).'),
    'mpa-pan': ('MPA Singapore · Pre-arrival notification of security',
        'https://www.mpa.gov.sg/port-marine-ops/port-safety-security/declaration-of-pre-arrival-notification',
        'Ships calling at Singapore must send a security Pre-Arrival Notification to MPA’s Port Security Unit at least '
        '24 hours before arrival.'),
    'imo-imdg': ('IMO · IMDG Code', 'https://www.imo.org/en/publications/pages/imdg%20code.aspx',
        'The IMDG Code (Amendment 42-24) is mandatory from 1 January 2026 for packaged dangerous goods carried by sea, '
        'covering classification, packing, marking, labelling, documentation, stowage and segregation.'),
    'mpa-declaring-dg': ('MPA Singapore · Declaring dangerous goods',
        'https://www.mpa.gov.sg/port-marine-ops/operations/gas-free-hazardous-cargo-info/declaring-dangerous-goods',
        'Dangerous goods on board must be declared through digitalPORT@SG at least 24 hours before the vessel arrives, '
        'or 24 hours before loading when the vessel is already in port.'),
}


def enabled(request):
    return request.demo_research and (request.route_request.origin, request.route_request.destination) == DEMO_PAIR


def _official(checked_at, *keys):
    return [{'id': key, 'title': SOURCES[key][0], 'url': SOURCES[key][1], 'supportingPassage': SOURCES[key][2],
             'retrievedAt': checked_at, 'authority': 'official'} for key in keys]


def _finding(category, port_id, route_ids, title, explanation, action, *, severity='yellow',
             missing=(), evidence=(), vessel_imo=None):
    port_ids = list(port_id) if isinstance(port_id, tuple) else [port_id]
    return {
        'id': sha256(f'demo:{category}:{port_ids}:{title}'.encode()).hexdigest()[:20],
        'category': category, 'severity': severity, 'status': 'confirmed', 'demo': True,
        'title': title,
        'explanation': explanation,
        'recommendedAction': action,
        'scope': {'routeIds': route_ids, 'portRoles': ['departure' if value == 'FRLEH' else 'arrival'
                  for value in port_ids], 'portIds': port_ids, 'cargoItemIds': [], 'vesselImo': vessel_imo},
        'cost': None, 'evidenceIds': [item['id'] for item in evidence],
        'evidence': list(evidence), 'missingInputs': list(missing),
    }


def _uploaded_evidence(references, page, checked_at):
    reference = next((item for item in references
                      if (item.get('page') if isinstance(item, dict) else item.page) == page), None)
    if reference is None:
        return []
    if not isinstance(reference, dict):
        reference = reference.model_dump(mode='json', by_alias=True)
    return [{'id': reference['id'], 'title': reference['title'], 'documentId': reference['id'],
             'pageOrSection': f'Page {page}', 'supportingPassage': reference['text'][:4000],
             'retrievedAt': checked_at, 'authority': 'user_document'}]


def _imo_check_digit(imo):
    """IMO numbers end in a check digit: the last digit of the six leading digits weighted 7..2."""
    digits = [int(c) for c in imo[:6]]
    return sum(d * w for d, w in zip(digits, range(7, 1, -1))) % 10


def _allowances(report):
    labels = {'fastest': 'Fastest', 'economical': 'Cheapest', 'lowest_emissions': 'Lowest CO₂'}
    parts = [f"{labels.get(r.get('strategy'), r['id'])} {round(r['emissions']['co2Tonnes'] / 2):,} t"
             for r in report['routes'] if r.get('emissions', {}).get('co2Tonnes')]
    return ' · '.join(parts)


def assessments(report, context_sha, cargo_text='', document_references=(), imo_number=None):
    route_ids = [route['id'] for route in report['routes']]
    document_references = list(document_references)
    supplied_text = cargo_text or '\n'.join(ref.get('text', '') if isinstance(ref, dict) else ref.text
                                        for ref in document_references)
    manifest_case = all(marker in supplied_text for marker in ('SS-2026-001', 'SPE-LFP-2026', '3480'))
    now = datetime.now(UTC)
    checked_at = now.isoformat()
    if manifest_case:
        citations = {page: _uploaded_evidence(document_references, page, checked_at)
                     for page in (4, 5, 7, 8, 9, 10, 11, 12, 13, 14)}
        official = lambda *keys: _official(checked_at, *keys)
        allowances = _allowances(report)
        imo_valid = bool(imo_number) and imo_number.isdigit() and len(imo_number) == 7 \
            and _imo_check_digit(imo_number) == int(imo_number[6])
        sanctions = [
            _finding('sanctions', ('FRLEH', 'SGSIN'), route_ids, f'IMO {imo_number} fails the check digit' if imo_number else 'Vessel IMO number missing',
                (f'IMO numbers end in a check digit derived from the first six digits [imo-number]. For {imo_number} the check digit should be {_imo_check_digit(imo_number)}, '
                 f'so {imo_number} is not a valid IMO number. Public AIS listings show {imo_number} broadcast by CM SHENZHEN (MMSI 412123000, China flag), '
                 'not the Singapore-flagged MV PACIFIC HORIZON named in the manifest. An invalid or mismatched ship identity is a recognised sanctions-evasion red flag.'
                 if imo_number and not imo_valid else
                 'The manifest lists MV PACIFIC HORIZON without an IMO number, the permanent identifier needed to screen a ship [imo-number].'),
                'Obtain the ship’s IMO number from its registry certificate, confirm it against the flag registry, and rescreen before booking.',
                severity='red', evidence=official('imo-number') + citations[4], vessel_imo=imo_number),
            _finding('sanctions', ('FRLEH', 'SGSIN'), route_ids, 'No sanctions-list matches',
                f'As of 25 October 2026, IMO {imo_number or "(none)"}, MV PACIFIC HORIZON, Shanghai Pacific Energy Storage Co., Ltd. and Rotterdam Energy Distribution B.V. '
                'have no matches on the OFAC SDN List [ofac-search], the UN Security Council Consolidated List [un-list] or the EU financial sanctions list [eu-sanctions-map].',
                'Repeat the screening against the corrected IMO and the ship’s registered owner and operator at booking.',
                severity='info', evidence=official('ofac-search', 'un-list', 'eu-sanctions-map') + citations[14], vessel_imo=imo_number),
        ]
        rows = {
            'security': [
                _finding('security', 'FRLEH', route_ids, 'War-risk and battery cover not confirmed',
                    'Policy INS-2026-1042 insures the battery modules for USD 528,000 (110% of the USD 480,000 cargo value), but war-risk cover is still subject to route verification and dangerous-goods cover to insurer confirmation. '
                    'Via Suez the voyage transits the Red Sea and Gulf of Aden, both Joint War Committee Listed Areas that require notice to underwriters and an additional premium [jwc].',
                    'Have the policy endorsed for Le Havre to Singapore, including war risk for the transit and Class 9 lithium battery cargo; register with UKMTO when entering the Voluntary Reporting Area [ukmto].',
                    evidence=official('jwc', 'ukmto') + citations[14]),
                _finding('security', 'SGSIN', route_ids, 'Singapore security pre-arrival notification',
                    'MV PACIFIC HORIZON must send a security Pre-Arrival Notification to MPA’s Port Security Unit at least 24 hours before arriving in Singapore [mpa-pan].',
                    'Have the ship’s agent submit the PAN with the ISSC, security level and last ten port calls 24 hours before ETA.',
                    severity='info', evidence=official('mpa-pan') + citations[4]),
            ],
            'environment': [
                _finding('environment', 'FRLEH', route_ids, 'EU ETS allowances for this voyage',
                    'MV PACIFIC HORIZON is 95,000 GT, above the 5,000 GT threshold, so 50% of its emissions from Le Havre to Singapore plus 100% at berth in Le Havre are in scope [eu-ets-shipping]. '
                    'For a 2026 voyage allowances cover 100% of those emissions, including methane and nitrous oxide, surrendered by 30 September 2027 [eu-ets-faq].' +
                    (f' On the calculated routes that is roughly {allowances} of CO₂ to cover with EUAs, before berth emissions.' if allowances else '') +
                    ('' if imo_valid else ' Emissions are reported per IMO number, so they cannot be attributed until the ship’s IMO is corrected.'),
                    'Budget EUAs for the shipping company’s share and record actual fuel consumption from departure.',
                    evidence=official('eu-ets-shipping', 'eu-ets-faq') + citations[5]),
                _finding('environment', 'FRLEH', route_ids, 'FuelEU Maritime GHG-intensity limit',
                    'FuelEU applies to 50% of the energy MV PACIFIC HORIZON uses on this outbound voyage, which must average no more than 89.34 gCO₂e/MJ over the year [fueleu].',
                    'Confirm the ship’s annual FuelEU compliance balance with Pacific Horizon Shipping.',
                    evidence=official('fueleu') + citations[5]),
                _finding('environment', 'FRLEH', route_ids, 'Mediterranean 0.10% sulphur limit',
                    'Via Suez the ship crosses the Mediterranean Emission Control Area, where fuel sulphur is capped at 0.10% since 1 May 2025 [med-eca].',
                    'Bunker compliant 0.10% fuel or confirm an approved scrubber, and log the changeover before entering the ECA.',
                    evidence=official('med-eca')),
            ],
            'trade': [
                _finding('trade', 'FRLEH', route_ids, 'EU export declaration for HS 8507.60',
                    'The 200 lithium-ion battery modules (HS 8507.60 [wco-hs], China origin, USD 480,000) leave the EU at Le Havre, so they need an export declaration and exit confirmation at the Le Havre office of exit [eu-customs-export]. '
                    'The manifest’s customs block is prepared for Dutch import (21% VAT, ICS2 entry summary), which does not apply to this voyage.',
                    'Lodge the export declaration with HS 8507.60, origin certificate COO-2026-1042 and the commercial invoice before the terminal cut-off.',
                    evidence=official('eu-customs-export', 'wco-hs') + citations[8] + citations[12] + citations[13]),
                _finding('trade', 'SGSIN', route_ids, 'Singapore import: no duty, 9% GST',
                    'Lithium-ion battery modules are not dutiable in Singapore; GST of 9% is payable on the CIF value [sg-duties]. On the declared USD 480,000 that is about USD 43,200 before freight and insurance are added. '
                    'The consignee must obtain an import permit through TradeNet before import [sg-customs-import].',
                    'Restate the customs value on a CIF Singapore basis and have the declaring agent file the TradeNet permit with HS 8507.60 and China origin.',
                    evidence=official('sg-duties', 'sg-customs-import') + citations[8] + citations[13]),
            ],
            'sanctions': sanctions,
            'dangerous_goods': [
                _finding('dangerous_goods', 'FRLEH', route_ids, 'UN 3480 Class 9: 1,024 kWh of LFP modules',
                    '200 LiFePO4 modules of 5,120 Wh each (1,024 kWh total), packed 10 per wooden crate (600 kg), ship as UN 3480, LITHIUM ION BATTERIES, Class 9 under IMDG Amendment 42-24 [imo-imdg]: '
                    'packing instruction P903, EmS F-A, S-I, stowage category A. The dangerous-goods declaration DGD-2026-1042 is still a draft and crate compliance with P903 is not yet confirmed.',
                    'Finalise and sign DGD-2026-1042, confirm the crates meet P903, keep the UN 38.3 test summary UN38-2026-1042 available, and submit the 15,900 kg VGM before the Le Havre cut-off.',
                    severity='red', evidence=official('imo-imdg') + citations[7] + citations[9] + citations[10] + citations[11] + citations[12]),
                _finding('dangerous_goods', 'SGSIN', route_ids, 'Declare UN 3480 cargo to MPA 24 hours ahead',
                    'The Class 9 battery container must be declared to MPA through digitalPORT@SG at least 24 hours before MV PACIFIC HORIZON arrives in Singapore [mpa-declaring-dg].',
                    'Send the final declaration to the carrier so the ship’s agent can file it on digitalPORT@SG before arrival.',
                    evidence=official('mpa-declaring-dg') + citations[9]),
            ],
        }
        for category, findings in rows.items():
            yield {'category': category, 'status': 'completed', 'demo': True,
                   'summary': 'Findings for manifest SS-2026-001, confirmed against official sources.',
                   'coverageNotes': [],
                   'findings': findings, 'seconds': 0, 'contextSha256': context_sha}
    else:
        yield from _generic_assessments(route_ids, context_sha, imo_number)

    expiry = now + timedelta(hours=1)
    congestion = []
    for port_id, port_name, level, alternative_id, alternative_name in (
        ('FRLEH', 'Le Havre', 'mild', 'BEANR', 'Antwerpen'),
        ('SGSIN', 'Singapore', 'high', 'MYTPP', 'Tanjung Pelepas'),
    ):
        congestion.append({
                   'portId': port_id, 'portName': port_name, 'level': level, 'demo': True,
                   'basis': 'unknown', 'confidence': 'low',
                   'summary': f'{port_name} may have a berth delay.',
                   'evidenceAsOf': None, 'checkedAt': now.isoformat(), 'refreshAfter': expiry.isoformat(),
                   'sources': [], 'qualityNotes': ['No live evidence or wait-time estimate.'],
                   'researchStatus': 'completed', 'display': {'showBadge': True,
                       'color': 'red' if level == 'high' else 'yellow', 'label': 'Congestion'},
                   'cached': True, 'alternativePort': {
                       'portId': alternative_id, 'name': alternative_name,
                       'reason': 'Candidate for a live reroute calculation.',
                       'congestionLevel': 'unknown',
                       'status': 'candidate', 'onwardTransport': None,
                   },
               })
    yield {'category': 'congestion', 'status': 'completed', 'demo': True,
           'summary': 'No current port conditions are asserted.',
           'coverageNotes': [], 'findings': [],
           'contextSha256': context_sha, 'assessments': congestion}


def _generic_assessments(route_ids, context_sha, imo_number):
    rows = {
        'security': [
            ('FRLEH', 'War-risk cover for a Suez routing',
             'Via Suez the voyage transits the Red Sea and Gulf of Aden, both Joint War Committee Listed Areas, so underwriters must be notified and charge an additional war-risk premium [jwc]. '
             'A Cape of Good Hope routing avoids the listed areas at the cost of extra distance.',
             'Obtain the war-risk quote before fixing the routing and register with UKMTO when entering the Voluntary Reporting Area [ukmto].', 'yellow', ('jwc', 'ukmto')),
            ('SGSIN', 'Singapore security pre-arrival notification',
             'Ships calling at Singapore must send a security Pre-Arrival Notification to MPA’s Port Security Unit at least 24 hours before arrival [mpa-pan].',
             'Have the ship’s agent submit the PAN with the ISSC, security level and last ten port calls 24 hours before ETA.', 'info', ('mpa-pan',)),
        ],
        'environment': [
            ('FRLEH', 'EU ETS: 50% of voyage emissions',
             'Ships of 5,000 GT and above leaving an EU port are in EU ETS scope: 50% of emissions from Le Havre to Singapore plus 100% at berth in Le Havre [eu-ets-shipping]. '
             'For 2026 voyages allowances cover 100% of those emissions, including methane and nitrous oxide, surrendered by 30 September 2027 [eu-ets-faq].',
             'Monitor fuel consumption from departure and budget EU allowances for half of the voyage’s CO₂e.', 'yellow', ('eu-ets-shipping', 'eu-ets-faq')),
            ('FRLEH', 'FuelEU Maritime GHG-intensity limit',
             'FuelEU applies to 50% of the energy used on this outbound voyage, which must average no more than 89.34 gCO₂e/MJ over the year [fueleu].',
             'Confirm the ship’s annual FuelEU compliance balance with the operator.', 'yellow', ('fueleu',)),
            ('FRLEH', 'Mediterranean 0.10% sulphur limit',
             'Via Suez the ship crosses the Mediterranean Emission Control Area, where fuel sulphur is capped at 0.10% since 1 May 2025 [med-eca].',
             'Bunker compliant 0.10% fuel or confirm an approved scrubber, and log the changeover before entering the ECA.', 'yellow', ('med-eca',)),
        ],
        'trade': [
            ('FRLEH', 'EU export declaration at Le Havre',
             'Goods leaving the EU are placed under the export procedure with an export declaration, and exit is confirmed at the customs office of exit in Le Havre [eu-customs-export].',
             'Lodge the export declaration with HS codes [wco-hs], origin and value before the terminal cut-off.', 'yellow', ('eu-customs-export', 'wco-hs')),
            ('SGSIN', 'Singapore import permit and 9% GST',
             'An import permit must be obtained through TradeNet before import [sg-customs-import]. Only liquor, tobacco, motor vehicles and petroleum are dutiable; GST of 9% is payable on the CIF value [sg-duties].',
             'Have the consignee’s declaring agent file the TradeNet permit with HS code, origin and CIF value.', 'yellow', ('sg-customs-import', 'sg-duties')),
        ],
        'sanctions': [
            ('SGSIN', 'Screen vessel and shipment parties',
             'Vessels are screened by IMO number [imo-number] against the OFAC SDN List [ofac-search] and EU restrictive measures [eu-sanctions-map].',
             'Screen the vessel, registered owner, operator and counterparties against both lists before booking.', 'yellow', ('imo-number', 'ofac-search', 'eu-sanctions-map')),
        ],
        'dangerous_goods': [
            ('FRLEH', 'Classify cargo under IMDG 42-24',
             'Packaged dangerous goods carried by sea must follow IMDG Code Amendment 42-24, mandatory since 1 January 2026 [imo-imdg].',
             'Check each item’s UN number and class from its safety data sheet before booking.', 'yellow', ('imo-imdg',)),
            ('SGSIN', 'Declare dangerous goods to MPA 24 hours ahead',
             'Any dangerous goods on board must be declared through digitalPORT@SG at least 24 hours before arrival in Singapore [mpa-declaring-dg].',
             'Confirm with the carrier whether the container carries declarable goods.', 'info', ('mpa-declaring-dg',)),
        ],
    }
    checked_at = datetime.now(UTC).isoformat()
    for category, entries in rows.items():
        findings = [_finding(category, port_id, route_ids, title, explanation, action, severity=severity,
                             evidence=_official(checked_at, *keys),
                             vessel_imo=imo_number if category == 'sanctions' else None)
                    for port_id, title, explanation, action, severity, keys in entries]
        yield {'category': category, 'status': 'completed', 'demo': True,
               'summary': 'Findings confirmed against official sources.',
               'coverageNotes': [],
               'findings': findings, 'seconds': 0, 'contextSha256': context_sha}
