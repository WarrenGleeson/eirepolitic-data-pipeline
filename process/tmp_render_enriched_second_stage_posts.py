#!/usr/bin/env python3
from __future__ import annotations

import io
import json
from datetime import date
from pathlib import Path

import boto3
import pandas as pd
from PIL import Image, ImageDraw

import process.tmp_render_all_second_stage_posts as renderer
from extract.oireachtas.batch import resolve_production_key

ENRICH = Path('artifacts/second-stage-enrichment/copy.json')
ASSET_DIR = Path('instagram/templates/assets')
if not ENRICH.is_file():
    raise SystemExit(f'missing enrichment dataset: {ENRICH}')

data = json.loads(ENRICH.read_text(encoding='utf-8'))
rows = data.get('rows', [])
if len(rows) != 108:
    raise SystemExit(f'expected 108 enrichment rows, got {len(rows)}')
by_id = {r['bill_id']: r for r in rows}

# Office-holders verified against official gov.ie material for the relevant 2025-26 introduction dates.
MINISTER_OFFICEHOLDERS = {
    'Minister for Children, Disability and Equality': 'Norma Foley TD',
    'Minister for Culture, Communications and Sport': 'Patrick O’Donovan TD',
    'Minister for Health': 'Jennifer Carroll MacNeill TD',
    'Minister for Justice, Home Affairs and Migration': 'Jim O’Callaghan TD',
    'Minister for Transport': 'Darragh O’Brien TD',
}

_original_generic = renderer.generic_copy
_original_load_rows = renderer.load_rows


def enriched_generic(row):
    item = by_id.get(str(row.get('bill_id', '')))
    if not item:
        return _original_generic(row)
    vals = tuple(str(item.get(k, '')).strip() for k in ('what', 'practical', 'context', 'issues'))
    return vals if all(vals) else _original_generic(row)


def _read_latest_csv(key: str) -> pd.DataFrame:
    s3 = boto3.client('s3', region_name='ca-central-1')
    real = resolve_production_key(s3, bucket=renderer.BUCKET, production_key=key)
    obj = s3.get_object(Bucket=renderer.BUCKET, Key=real)
    return pd.read_csv(io.BytesIO(obj['Body'].read()), dtype=str, keep_default_na=False)


def enriched_load_rows():
    bill_rows, production_key = _original_load_rows()
    bridge = _read_latest_csv(renderer.KEYS['bridge'])
    speeches = _read_latest_csv(renderer.KEYS['speeches'])
    sponsors = _read_latest_csv('processed/oireachtas_unified/latest/csv/silver_bill_sponsors.csv')

    latest_debate = {}
    if {'bill_id', 'debate_section_id'}.issubset(bridge.columns) and {'debate_section_id', 'debate_date'}.issubset(speeches.columns):
        joined = bridge[['bill_id', 'debate_section_id']].drop_duplicates().merge(
            speeches[['debate_section_id', 'debate_date']].drop_duplicates(),
            on='debate_section_id', how='inner'
        )
        joined['_date'] = pd.to_datetime(joined['debate_date'], errors='coerce')
        joined = joined.dropna(subset=['_date'])
        if not joined.empty:
            latest_debate = joined.groupby('bill_id')['_date'].max().dt.strftime('%Y-%m-%d').to_dict()

    primary = sponsors[sponsors['is_primary'].astype(str).str.lower().eq('true')].copy()
    primary_map = {}
    for _, pr in primary.iterrows():
        primary_map[str(pr.get('bill_id', ''))] = {
            'name': str(pr.get('sponsor_name', '')).strip(),
            'role': str(pr.get('sponsor_role_name', '')).strip(),
        }

    for row in bill_rows:
        bid = str(row.get('bill_id', ''))
        row['latest_debate_date'] = latest_debate.get(bid, '')
        p = primary_map.get(bid, {})
        row['resolved_sponsor_name'] = p.get('name', '')
        row['resolved_sponsor_role'] = p.get('role', '')
        role = row['resolved_sponsor_role']
        if role in MINISTER_OFFICEHOLDERS:
            row['resolved_sponsor_name'] = MINISTER_OFFICEHOLDERS[role]
            row['sponsor_display_type'] = 'Government Bill'
        else:
            if not row['resolved_sponsor_name']:
                row['resolved_sponsor_name'] = str(row.get('primary_sponsor_name', '')).strip()
            if not role:
                role = str(row.get('primary_sponsor_role_name', '')).strip()
                row['resolved_sponsor_role'] = role
            row['sponsor_display_type'] = 'Private Member’s Bill' if row['resolved_sponsor_name'] else 'Bill sponsor'
    return bill_rows, production_key


def _parse(value):
    if not value:
        return None
    ts = pd.to_datetime(str(value), errors='coerce')
    if pd.isna(ts):
        return None
    return ts.date()


def _fmt_date(value) -> str:
    d = _parse(value)
    return d.strftime('%-d %B %Y') if d else ''


def _duration(start, end) -> str:
    a = _parse(start); b = _parse(end)
    if not a or not b or b < a:
        return ''
    days = (b - a).days
    if days < 14:
        return f'{days} day' + ('' if days == 1 else 's')
    if days < 60:
        weeks = max(2, days // 7)
        return f'{weeks} weeks'
    months = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        months = max(0, months - 1)
    if months < 12:
        return f'{max(1, months)} month' + ('' if months == 1 else 's')
    years, rem = divmod(months, 12)
    if rem == 0:
        return f'{years} year' + ('' if years == 1 else 's')
    return f'{years} year' + ('' if years == 1 else 's') + f', {rem} month' + ('' if rem == 1 else 's')


def _house_plain(value: str) -> str:
    low = str(value or '').lower()
    if 'dáil' in low or 'dail' in low:
        return 'Dáil'
    if 'seanad' in low:
        return 'Seanad'
    return 'House'


def status_parts(row):
    snapshot = row.get('snapshot_date') or date.today().isoformat()
    stage_date = row.get('current_stage_date', '')
    debate_date = row.get('latest_debate_date', '')
    division_date = row.get('latest_division_date', '')
    last_event = row.get('last_event_date', '')
    house = _house_plain(row.get('current_stage_house_name', ''))
    outcome = str(row.get('current_stage_outcome', '') or '').strip().lower()

    duration = _duration(stage_date, snapshot) or 'an unknown length of time'
    headline = f'AT SECOND STAGE FOR {duration.upper()}'
    entered = f'Reached Second Stage: {_fmt_date(stage_date)}' if _fmt_date(stage_date) else 'Reached Second Stage: date not available'

    candidates = []
    for kind, value in [('stage', stage_date), ('debate', debate_date), ('vote', division_date), ('update', last_event)]:
        d = _parse(value)
        if d:
            candidates.append((d, kind, value))
    candidates.sort(key=lambda x: (x[0], {'stage': 0, 'debate': 2, 'vote': 1, 'update': 3}[x[1]]))
    last_date, kind, raw = candidates[-1] if candidates else (None, '', '')

    dd = _parse(debate_date)
    if dd and last_date and dd == last_date:
        kind, raw = 'debate', debate_date
    vd = _parse(division_date)
    if vd and last_date and vd == last_date and not (dd and dd == last_date):
        kind, raw = 'vote', division_date

    pretty = _fmt_date(raw)
    if kind == 'debate':
        activity = f'Last activity: The Bill was discussed in the {house} on {pretty}.'
    elif kind == 'vote':
        activity = f'Last activity: A recorded vote linked to the Bill took place on {pretty}.'
    elif kind == 'update':
        activity = f'Last activity: The latest recorded update for the Bill was on {pretty}.'
    elif kind == 'stage':
        activity = f'Last activity: The Bill reached Second Stage on {pretty}.'
    else:
        activity = 'Last activity: No later activity is recorded.'

    if 'adjourn' in outcome:
        follow = 'The debate was paused before it finished, and no later progress is recorded.'
        reason = ''
    elif 'postpon' in outcome or 'defer' in outcome:
        follow = 'Further consideration was postponed, and no later progress is recorded.'
        reason = ''
    else:
        since = _duration(raw, snapshot) if raw else ''
        if kind == 'debate' and since:
            follow = f'It has remained at Second Stage for {since} since that discussion.'
        elif kind in {'update', 'vote'} and since:
            follow = f'No move to the next stage is recorded in the {since} since then.'
        elif kind == 'stage':
            follow = 'There is no recorded Second Stage debate yet, and it has not moved to the next stage.'
        else:
            follow = 'It has not moved to the next stage.'
        reason = 'The official record does not say why it has not progressed further.'
    return headline, entered, activity, follow, reason


def _is_gold(px):
    rr, gg, bb, aa = px
    return aa != 0 and rr > 150 and gg > 105 and bb < 155 and (rr - bb) > 55 and (gg - bb) > 20


def _clean_corner(path: Path) -> Image.Image:
    src = Image.open(path).convert('RGBA'); out = src.copy(); pix = out.load()
    for yy in range(out.height):
        for xx in range(out.width):
            if _is_gold(pix[xx, yy]):
                pix[xx, yy] = (15, 47, 36, 255)
    return out


def clean_bill_base() -> Image.Image:
    im = Image.new('RGB', (renderer.W, renderer.H), renderer.BG)
    placements = [('corner_tl.png', (0, 0)), ('corner_tr.png', (925, 0)), ('corner_bl.png', (0, 1195)), ('corner_br.png', (925, 1195))]
    for name, pos in placements:
        c = _clean_corner(ASSET_DIR / name).resize((155, 155), Image.Resampling.LANCZOS)
        im.paste(c, pos, c)
    return im


def _draw_sponsor_box(d, row, top, bottom):
    renderer.panel(d, (58, top, 1022, bottom), outline=renderer.OUTLINE, fill=renderer.PANEL, w=2)
    d.text((86, top + 18), 'BROUGHT BY', font=renderer.font(17, True), fill=renderer.ACCENT, anchor='la')
    name = str(row.get('resolved_sponsor_name', '')).strip() or 'Sponsor not named in the record'
    role = str(row.get('resolved_sponsor_role', '')).strip()
    bill_type = str(row.get('sponsor_display_type', '')).strip()
    name_font = renderer.fit(d, name, 760, 36, 27, 18, 2, True)
    renderer.draw_block(d, name, (86, top + 50, 865, top + 92), name_font, fill=renderer.TEXT, center=False)
    if role:
        role_font = renderer.fit(d, role, 760, 34, 19, 14, 2, False)
        renderer.draw_block(d, role, (86, top + 87, 865, top + 126), role_font, fill=renderer.MUTED, center=False)
    d.text((994, bottom - 23), bill_type, font=renderer.font(15, True), fill=renderer.MUTED, anchor='ra')


def enriched_bill_slide(out, idx, row):
    im = clean_bill_base(); d = ImageDraw.Draw(im)
    title = row['title']
    tf = renderer.fit(d, title, 900, 105, 34, 20, 3, True)
    lines = renderer.wrap_text_px(d, title, tf, 900)
    cur = 46
    for ln in lines:
        d.text((renderer.W // 2, cur), ln, font=tf, fill=renderer.TEXT, anchor='ma')
        bb = d.textbbox((renderer.W // 2, cur), ln, font=tf, anchor='ma')
        cur = bb[3] + 3

    # Approved title treatment: one clean centred gold rule only.
    line_y = max(126, cur + 5)
    d.rectangle((190, line_y, 890, line_y + 4), fill=renderer.ACCENT)

    ry = line_y + 16
    meta = f"Bill No. {row.get('bill_no','')} of {row.get('bill_year','')} · {row.get('origin_house_name','')}"
    mf = renderer.fit(d, meta, 900, 36, 18, 13, 2)
    renderer.draw_block(d, meta, (90, ry, 990, ry + 38), mf, fill=renderer.MUTED, center=True)

    texts = renderer.SPECIAL.get(title) or enriched_generic(row)
    labels = ['WHAT THE BILL COVERS', 'PRACTICAL EFFECT', 'SPONSOR / CONTEXT', 'SECOND STAGE RECORD']
    top = ry + 46; bh = 276; gap = 18
    boxes = [(58, top, 518, top + bh), (562, top, 1022, top + bh), (58, top + bh + gap, 518, top + 2 * bh + gap), (562, top + bh + gap, 1022, top + 2 * bh + gap)]
    shared = 14
    for size in range(24, 13, -1):
        ff = renderer.font(size)
        if all(renderer.lines_h(d, renderer.wrap_text_px(d, txt, ff, 408), ff, 4) <= 185 for txt in texts):
            shared = size; break
    bf = renderer.font(shared)
    for box, label, txt in zip(boxes, labels, texts):
        renderer.panel(d, box)
        d.text((box[0] + 22, box[1] + 18), label, font=renderer.font(16, True), fill=renderer.ACCENT, anchor='la')
        end = renderer.draw_block(d, txt, (box[0] + 22, box[1] + 55, box[2] - 22, box[3] - 16), bf)
        if end > box[3] - 10:
            raise RuntimeError(f'overflow {title} {label} at shared font {shared}')

    # Reserve a dedicated sponsor box at the bottom; status takes the remaining space above it.
    sponsor_bottom = 1206
    sponsor_top = 1052
    status_top = boxes[2][3] + 20
    status_bottom = sponsor_top - 16
    if status_bottom - status_top < 165:
        # Compress explainer rows slightly for unusually tall title blocks.
        raise RuntimeError(f'insufficient status height for {title}: {status_bottom-status_top}')

    renderer.panel(d, (58, status_top, 1022, status_bottom), outline=renderer.ACCENT, fill=renderer.BG, w=3)
    d.text((renderer.W // 2, status_top + 18), 'SECOND STAGE STATUS', font=renderer.font(17, True), fill=renderer.ACCENT, anchor='ma')
    headline, entered, activity, follow, reason = status_parts(row)
    hf = renderer.fit(d, headline, 850, 34, 26, 20, 2, True)
    d.text((renderer.W // 2, status_top + 52), headline, font=hf, fill=renderer.TEXT, anchor='ma')
    status_lines = [x for x in (entered, activity, follow, reason) if x]
    available_h = status_bottom - (status_top + 80) - 10
    joined = ' '.join(status_lines)
    sf = renderer.fit(d, joined, 850, available_h, 20, 13, 9)
    y = status_top + 79
    for line in status_lines:
        for sub in renderer.wrap_text_px(d, line, sf, 850):
            d.text((renderer.W // 2, y), sub, font=sf, fill=renderer.TEXT, anchor='ma')
            bb = d.textbbox((renderer.W // 2, y), sub, font=sf, anchor='ma')
            y = bb[3] + 2
        y += 1
    if y > status_bottom - 7:
        raise RuntimeError(f'status overflow {title}: y={y}, bottom={status_bottom}')

    _draw_sponsor_box(d, row, sponsor_top, sponsor_bottom)

    # Approved footer treatment: one clean centred gold rule only.
    footer_y = 1253
    d.rectangle((190, footer_y, 890, footer_y + 4), fill=renderer.ACCENT)
    d.text((64, 1278), f"Source: Houses of the Oireachtas · {row.get('bill_id','')}", font=renderer.font(12), fill=renderer.MUTED, anchor='la')
    d.text((1016, 1278), f'Second Stage · Bill {idx}', font=renderer.font(12, True), fill=renderer.MUTED, anchor='ra')
    im.save(out / f'{idx:02d}-bill.png')


renderer.generic_copy = enriched_generic
renderer.load_rows = enriched_load_rows
renderer.bill_slide = enriched_bill_slide
renderer.main()
