"""Fast, source-backed document list for the Le Havre to Singapore presentation."""


def documents(actions):
    """Tie real public references to findings; issued documents remain to obtain."""
    by_category = {}
    for action in actions:
        by_category.setdefault(action['category'], []).append(action['id'])
    specs = (
        ('dangerous-goods-declaration', 'Dangerous goods transport declaration', ('dangerous_goods',), ['FRLEH', 'SGSIN'],
         'IMO IMDG Code amendment and multimodal dangerous goods form', 'https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/IndexofIMOResolutions/MSCResolutions/MSC.556%28108%29.pdf',
         'Shipper and carrier must complete and sign the applicable declaration; the linked IMO PDF is the published reference, not a completed declaration.'),
        ('singapore-dg-notice', 'Singapore dangerous goods arrival notice', ('dangerous_goods',), ['SGSIN'],
         'Singapore MPA dangerous goods declaration instructions', 'https://www.mpa.gov.sg/port-marine-ops/operations/gas-free-hazardous-cargo-info/declaring-dangerous-goods',
         'Vessel owner, agent or master submits through the terminal or port channel specified by MPA.'),
        ('singapore-import', 'Singapore import permit and classification check', ('trade',), ['SGSIN'],
         'Singapore Customs import procedures', 'https://www.customs.gov.sg/doing-business/import-operations/import-procedures/import-procedures-overview/',
         'Importer or declaring agent obtains the actual permit after confirming HS classification and cargo details.'),
        ('eu-mrv', 'Ship emissions monitoring records', ('environment',), ['FRLEH'],
         'European Commission maritime monitoring-plan guidance', 'https://climate.ec.europa.eu/document/download/f4f95ee6-50ee-4c4f-a0f6-b04b78df46b6_en?filename=policy_transport_shipping_gd2_approval_mps_en.pdf',
         'Ship operator supplies the actual verified records; the Commission PDF is guidance only.'),
    )
    result = []
    for slug, title, categories, ports, source_title, url, instruction in specs:
        ids = list(dict.fromkeys(i for category in categories for i in by_category.get(category, [])))
        if not ids:
            continue
        evidence = {'id': 'official-' + slug, 'title': source_title, 'url': url,
            'retrievedAt': '2026-10-25T00:00:00Z', 'authority': 'official'}
        result.append({'id': 'reference-' + slug, 'title': title, 'portIds': ports,
            'missingInputs': [], 'evidence': [evidence], 'applicability': 'to_verify',
            'purpose': 'Prepare or verify this voyage document using the linked authority publication.',
            'provider': 'Shipper, importer, vessel operator or authorised agent, as applicable.',
            'timing': 'Confirm the current deadline with the relevant authority or terminal.',
            'obtainInstructions': instruction,
            'actionIds': ids, 'downloadAssets': [{'title': source_title, 'kind': 'reference', 'evidence': evidence}]})
    return result
