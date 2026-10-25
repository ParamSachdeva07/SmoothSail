"""Printable checklist; only trusted snapshots and bounded user progress are accepted."""
from html import escape
from io import BytesIO
import re
from urllib.parse import urlsplit

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, KeepTogether, HRFlowable

LABELS = {'security': 'Security & insurance', 'environment': 'Environment & emissions', 'trade': 'Customs & port charges',
          'sanctions': 'Sanctions & registry', 'dangerous_goods': 'Dangerous goods', 'congestion': 'Port operations'}


def plain(value):
    # Keep text readable in built-in portable PDF fonts; no model-authored XML.
    value = str(value or '').replace('₂', '2').replace('→', ' to ').replace('✓', 'Completed').replace('•', '-')
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    return value.replace('**', '').replace('`', '')


def render_pdf(checklist, checked=(), notes=None):
    buffer, notes, checked = BytesIO(), notes or {}, set(checked)
    styles = getSampleStyleSheet()
    styles['Title'].alignment = TA_LEFT
    styles['Title'].textColor = colors.HexColor('#123DFF')
    styles['Title'].fontName = 'Times-Roman'
    styles.add(ParagraphStyle(name='BodySmall', fontName='Helvetica', fontSize=9, leading=13, spaceAfter=7,
                              wordWrap='LTR', splitLongWords=True))
    styles.add(ParagraphStyle(name='Eyebrow', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#666666'), spaceAfter=6))
    styles.add(ParagraphStyle(name='ItemTitle', fontName='Helvetica-Bold', fontSize=11, leading=15, spaceBefore=12, spaceAfter=6, keepWithNext=True))
    styles.add(ParagraphStyle(name='SectionTitle', fontName='Times-Roman', fontSize=18, leading=22, spaceBefore=18, spaceAfter=10, keepWithNext=True))
    story, sources, numbers = [], [], {}
    def paragraph(text, style='BodySmall'):
        story.append(Paragraph(escape(plain(text)).replace('\n', '<br/>'), styles[style]))
    def field(label, value):
        if value:
            story.append(Paragraph('<b>' + escape(label) + ':</b> ' + escape(plain(value)).replace('\n', '<br/>'), styles['BodySmall']))
    def evidence(items):
        refs = []
        for source in items:
            key = (source.get('downloadPath') or source.get('url') or source.get('documentId') or source.get('id'), source.get('sourceVersion'))
            if key not in numbers:
                numbers[key] = len(sources) + 1
                sources.append(dict(source, sections=[]))
            stored = sources[numbers[key] - 1]
            section = source.get('pageOrSection')
            if section and section not in stored['sections']: stored['sections'].append(section)
            refs.append(str(numbers[key]))
        if refs: field('Sources', ', '.join(dict.fromkeys(refs)))
    def progress(item):
        paragraph(('[X] ' if item['id'] in checked else '[  ] ') + item['title'], 'ItemTitle')
        if item.get('portIds'): field('Port scope', ', '.join(item['portIds']))
    def tail(item):
        for value in item.get('missingInputs', []): field('Information needed', value)
        evidence(item.get('evidence', []))
        if notes.get(item['id']): field('Your notes', notes[item['id']])
    paragraph('SmoothSail', 'Title')
    paragraph('Voyage checklist', 'SectionTitle')
    voyage, route = checklist['voyage'], checklist['route']
    field('Voyage', f"{voyage.get('origin')} to {voyage.get('destination')}")
    field('Departure (UTC)', voyage.get('departureTime'))
    field('Selected route', f"{route.get('strategy', '')} / {checklist['routeId']}")
    field('Estimated arrival (UTC)', route.get('eta'))
    field('Generated (UTC)', checklist['generatedAt'])
    field('Progress', f"{len(checked)} checked / {len(checklist['actions']) + len(checklist['documents'])} items")
    paragraph(checklist['notice'], 'Eyebrow')
    if checklist['partial']: paragraph('PARTIAL SNAPSHOT: research was still running when this checklist was created.', 'Eyebrow')
    field('Document research', checklist['researchStatus'].replace('_', ' '))
    story.append(HRFlowable(width='100%', color=colors.HexColor('#dddddd')))
    paragraph('1. Recommended actions', 'SectionTitle')
    if not checklist['actions']: paragraph('No recommendations returned for this route. Review the coverage and gaps below.')
    for category in LABELS:
        items = [a for a in checklist['actions'] if a['category'] == category]
        if not items: continue
        category_start = len(story)
        paragraph(LABELS[category], 'Heading3')
        for index, item in enumerate(items):
            start = category_start if index == 0 else len(story)
            progress(item)
            field('Finding status', item['status'].replace('_', ' '))
            field('Action', item['action'])
            field('Why', item.get('explanation'))
            if item.get('origin') == 'operational_follow_up': paragraph('Operational follow-up derived from port congestion reporting.', 'Eyebrow')
            tail(item)
            story[start:] = [KeepTogether(story[start:])]
    documents_start = len(story)
    paragraph('2. Documents to prepare or verify', 'SectionTitle')
    if not checklist['documents']: paragraph('No documents verified in this research pass. This is not a declaration that no documents are required.')
    action_names = {a['id']: a['title'] for a in checklist['actions']}
    for index, item in enumerate(checklist['documents']):
        start = documents_start if index == 0 else len(story)
        progress(item)
        field('Applicability', item['applicability'].replace('_', ' '))
        field('Purpose', item['purpose'])
        field('Provider / issuer', item.get('provider') or 'Confirm with the responsible authority or provider.')
        field('Timing', item.get('timing') or 'Not verified; confirm before arranging shipment.')
        field('How to obtain', item.get('obtainInstructions') or 'Contact the responsible authority or provider.')
        field('Related actions', '; '.join(action_names[i] for i in item['actionIds'] if i in action_names))
        tail(item)
        story[start:] = [KeepTogether(story[start:])]
    paragraph('3. Research coverage & unresolved information', 'SectionTitle')
    for check in checklist['coverage']:
        field(LABELS.get(check['category'], check['category']), check['status'].replace('_', ' ') + ' — ' + check['summary'])
        for note in check.get('notes', []): paragraph(note)
    for gap in checklist['researchGaps']: paragraph('- ' + gap)
    sources_start = len(story)
    paragraph('4. Sources', 'SectionTitle')
    if not sources: paragraph('No supporting sources attached to the current recommendations.')
    for i, source in enumerate(sources, 1):
        start = sources_start if i == 1 else len(story)
        paragraph(f"[{i}] {source.get('title', 'Source')}", 'ItemTitle')
        field('Sections', ', '.join(source.get('sections', [])))
        field('Retrieved', source.get('retrievedAt'))
        field('Effective from', source.get('effectiveFrom'))
        version = source.get('sourceVersion')
        if version and not re.fullmatch(r'[0-9a-f]{32,64}', str(version)): field('Version', version)
        if source.get('downloadPath'): paragraph('Archived source document available from its citation in the app.', 'Eyebrow')
        url = str(source.get('url') or '')
        if urlsplit(url).scheme in ('http', 'https'):
            story.append(Paragraph(f'<link href="{escape(url, quote=True)}" color="#123DFF">Open original source</link>', styles['BodySmall']))
        # Keep each source together, including its link, and avoid dumping redirect tokens into the PDF.
        story[start:] = [KeepTogether(story[start:])]
    def footer(canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#777777'))
        canvas.drawString(42, 26, 'SmoothSail / Voyage checklist / Planning support')
        canvas.drawRightString(A4[0] - 42, 26, str(doc.page)); canvas.restoreState()
    SimpleDocTemplate(buffer, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=36, bottomMargin=48,
        title='SmoothSail voyage checklist', author='SmoothSail').build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
