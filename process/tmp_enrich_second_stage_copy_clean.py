#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

import process.tmp_enrich_second_stage_copy as base

# Patterns that indicate raw source-document leakage in automatically generated copy.
FORBIDDEN = [
    re.compile(r'_{3,}'),
    re.compile(r'(?i)meabhr[aá]n\s+m[ií]nitheach'),
    re.compile(r'(?i)mar\s+a\s+tionscna[ií]odh'),
    re.compile(r'(?i)as\s+initiated'),
    re.compile(r'(?i)\bacts?\s+referred\s+to\b'),
    re.compile(r'(?i)\bcontents\s+section\b'),
    re.compile(r'(?i)\bna\s+teachta[ií]\b|\bna\s+seanad[oó]ir[ií]\b'),
    re.compile(r'(?i)\bbill\s*\(as initiated\)\s*entitled\b'),
    re.compile(r'(?i)^short title(?:, citation and commencement| and commencement| and citation)?\b'),
    re.compile(r'(?i)^amendment of (?:principal )?act\b'),
    re.compile(r'(?i)^section\s+\d+\b'),
    re.compile(r'(?i)^part\s+\d+\b'),
]

# Stronger raw-frontmatter markers. These should never appear verbatim in public copy,
# but a clean human-written sentence may legitimately mention an explanatory memorandum.
RAW_MEMO_HEADING = re.compile(r'(?i)(?:^|\s)EXPLANATORY\s+MEMORANDUM(?:\s|$)')


def contaminated(text: str, *, manual: bool = False) -> bool:
    s = base.clean_text(text or '')
    if not s:
        return True
    if any(rx.search(s) for rx in FORBIDDEN):
        return True
    if not manual and RAW_MEMO_HEADING.search(s) and (
        s.isupper() or len(s.split()) < 18 or re.search(r'_{2,}|\bMEMORANDUM\s+EXPLANATORY\b', s, re.I)
    ):
        return True
    upper = s.upper()
    if ' AN BILLE ' in f' {upper} ' and ' BILL ' in f' {upper} ':
        return True
    words = re.findall(r"[A-Za-zÁÉÍÓÚáéíóú’'-]+", s)
    if len(words) < 7:
        return True
    return False


def clean_sentence_pool(text: str) -> list[str]:
    out = []
    for s in base.sentences(base.strip_frontmatter(text)):
        s = base.clean_text(s)
        if contaminated(s):
            continue
        low = s.lower()
        if re.match(r'^(section|part|chapter)\s+\d+\b', low):
            continue
        if low.startswith(('provisions of the bill', 'provisions the bill', 'background section')):
            continue
        out.append(s)
    return out


def choose(pool: list[str], keywords: tuple[str, ...], used: set[str]) -> str:
    best = ''
    best_score = -10_000
    for i, s in enumerate(pool):
        if s in used:
            continue
        low = s.lower()
        score = 100 - i
        if any(k in low for k in keywords):
            score += 35
        if len(s) > 360:
            score -= 10
        if score > best_score:
            best, best_score = s, score
    return best


def safe_build_copy(title: str, text: str, sponsor: str, has_memo: bool) -> dict:
    if title in base.MANUAL:
        result = {**base.MANUAL[title], 'confidence': 'manual', 'extracted_chars': len(text)}
        for field in ('what', 'practical', 'context', 'issues'):
            if contaminated(result[field], manual=True):
                raise RuntimeError(f'manual override contaminated: {title} / {field}')
        return result

    pool = clean_sentence_pool(text)
    used: set[str] = set()

    lt = base.long_title(text)
    if contaminated(lt):
        lt = ''
    purpose = base.memo_purpose(text)
    if contaminated(purpose):
        purpose = ''

    what_src = lt or purpose or choose(
        pool,
        ('purpose', 'would ', 'will ', 'seeks to', 'provide for', 'amend', 'establish', 'prohibit', 'require'),
        used,
    )
    if what_src:
        used.add(what_src)
        what = base.shorten(what_src, 300)
    else:
        what = f'The Bill proposes a legal change in the area described by its title: {title}.'

    practical_src = choose(
        pool,
        ('would ', 'will ', 'require', 'allow', 'permit', 'entitle', 'provide', 'establish', 'prohibit', 'remove', 'extend', 'reduce', 'increase'),
        used,
    )
    if practical_src:
        used.add(practical_src)
        practical = base.shorten(practical_src, 300)
    elif lt:
        practical = base.shorten(lt, 300)
    else:
        practical = 'The detailed legal effect is set out in the official Bill text.'

    context_src = choose(
        pool,
        ('background', 'respond', 'intended', 'aim', 'currently', 'existing', 'because', 'following', 'recommendation', 'concern'),
        used,
    )
    if context_src:
        context = base.shorten(context_src, 300)
    elif purpose and base.clean_text(purpose).lower() != base.clean_text(what).lower():
        context = base.shorten(purpose, 300)
    else:
        context = f'{sponsor} sponsors the Bill. The official Bill text sets out the proposed legal change; no wider political support is inferred from sponsorship.'

    issues = base.issues_from(text)
    result = {
        'what': what,
        'practical': practical,
        'context': context,
        'issues': issues,
        'confidence': 'high' if len(text) > 700 and (lt or purpose) else 'medium',
        'extracted_chars': len(text),
    }

    bad = [field for field in ('what', 'practical', 'context', 'issues') if contaminated(result[field])]
    if bad:
        if 'what' in bad:
            result['what'] = f'The Bill proposes a legal change in the area described by its title: {title}.'
        if 'practical' in bad:
            result['practical'] = 'The detailed legal effect is set out in the official Bill text.'
        if 'context' in bad:
            result['context'] = f'{sponsor} sponsors the Bill. The official record does not provide a clean plain-English background summary in the extracted source text.'
        if 'issues' in bad:
            result['issues'] = 'Second Stage can test the Bill’s overall approach, including its scope, implementation and safeguards.'
        result['confidence'] = 'medium'

    for field in ('what', 'practical', 'context', 'issues'):
        if contaminated(result[field]):
            raise RuntimeError(f'public copy still contaminated after fallback: {title} / {field} / {result[field]}')
    return result


base.build_copy = safe_build_copy
base.main()

out = json.loads((base.OUT / 'copy.json').read_text(encoding='utf-8'))
failures = []
for row in out.get('rows', []):
    is_manual = row.get('confidence') == 'manual'
    for field in ('what', 'practical', 'context', 'issues'):
        value = str(row.get(field, '') or '')
        if contaminated(value, manual=is_manual):
            failures.append({'title': row.get('title'), 'field': field, 'text': value})
(base.OUT / 'public_copy_gate.json').write_text(
    json.dumps({'failure_count': len(failures), 'failures': failures}, ensure_ascii=False, indent=2),
    encoding='utf-8',
)
if failures:
    raise SystemExit(f'public-copy contamination gate failed for {len(failures)} fields')
print('public-copy contamination gate passed: 0 contaminated fields')
