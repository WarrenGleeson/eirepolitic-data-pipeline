#!/usr/bin/env python3
from __future__ import annotations

import json
import re

import process.tmp_enrich_second_stage_copy as base

# Human-reviewed overrides for Bills where PDF extraction produced title-page,
# list-fragment, or cut-off sentence artifacts. Keep this set narrow and source-faithful.
EXTRA_MANUAL = {
    'Road Traffic (Amendment) (Jax’s Law) Bill 2026': {
        'what': 'Would allow cases where careless or dangerous driving causes the loss of a pregnancy to be prosecuted on indictment, giving higher courts wider sentencing powers.',
        'practical': 'It would expand the prosecution and sentencing options available when a crash causes pregnancy loss, rather than leaving those cases within the more limited summary framework.',
        'context': 'The Bill responds to calls for pregnancy loss caused by careless or dangerous driving to receive clearer recognition in road traffic law.',
        'issues': 'Second Stage can test how the proposal would interact with existing careless and dangerous driving offences, evidential requirements and sentencing.',
    },
    'Social Housing Passport Bill 2026': {
        'what': 'Would allow households on a local authority social housing waiting list to apply to move to another local authority list while carrying over their existing waiting time, subject to criteria set by the Minister.',
        'practical': 'People already receiving social housing support could also apply to join another local authority transfer list and carry over their time on the list, subject to the scheme rules.',
        'context': 'The Bill is sponsored by Eoin Ó Broin TD, Mark Ward TD and Louise O’Reilly TD and is intended to make it easier for households to move between local authority housing areas.',
        'issues': 'Second Stage can test the transfer criteria, how waiting time would be recognised between authorities, administrative coordination and eligibility safeguards.',
    },
    'Planning and Development (Provision of Public Housing) Bill 2026': {
        'what': 'Would amend the Planning and Development Act 2000 and repeal section 97(3)(b), changing the planning-law framework relevant to the provision of public housing.',
        'practical': 'The Bill would remove section 97(3)(b) from the 2000 Act, so the legal effect of that provision would no longer apply after commencement.',
        'context': 'The Bill is sponsored by Senators Chris Andrews, Maria McCormack, Joanne Collins, Pauline Tully, Conor Murphy and Nicole Ryan.',
        'issues': 'Second Stage can test the legal effect of the repeal, its interaction with existing planning and housing obligations, and implementation by planning authorities.',
    },
    'Health (Amendment) Bill 2026': {
        'what': 'Would amend Health Act 1970 provisions governing the supply without charge of certain drugs, medicines and medical or surgical appliances.',
        'practical': 'It would require the Minister for Health to carry out ongoing periodic reviews of how effectively the free-supply arrangements are operating.',
        'context': 'Under section 59 of the Health Act 1970, certain drugs, medicines and appliances can be supplied without charge to people covered by specified disease or disability arrangements.',
        'issues': 'Second Stage can test the scope of the review duty, how often reviews should occur, what evidence should be considered, and any cost or resourcing implications.',
    },
    'Comptroller and Auditor General (Due Diligence Complicity Audit) (Amendment) Bill 2026': {
        'what': 'Would give the Comptroller and Auditor General a role in carrying out a due-diligence and complicity audit connected with the use of public funds and resources and relevant international-law obligations.',
        'practical': 'The Comptroller and Auditor General would conduct the audit and report its findings to the Houses of the Oireachtas.',
        'context': 'The Bill draws on international legal analysis concerning obligations arising from the situation in the Occupied Palestinian Territory and Israel.',
        'issues': 'Second Stage can test the scope of the audit, the legal standards to be applied, the Comptroller and Auditor General’s powers and the reporting arrangements.',
    },
    'Valuation (Amendment) Bill 2026': {
        'what': 'Would amend valuation law so qualifying not-for-profit early childhood care and education premises are exempt from commercial rates, while excluding companies established for profit.',
        'practical': 'It would clarify that the exemption can cover aftercare and sessional or part-time early childhood services where the premises are occupied on a not-for-profit basis.',
        'context': 'The Bill changes the Schedule 4 exemptions that determine when property used for early childhood care and education is treated as non-rateable.',
        'issues': 'Second Stage can test the eligibility rules, the boundary between not-for-profit and for-profit providers, administration of the exemption and the effect on local authority rates income.',
    },
    'Forty-first Amendment of the Constitution (Right to Housing) Bill 2026': {
        'what': 'Would amend the Constitution by inserting a new Article 40A dealing with a right to housing.',
        'practical': 'It would create an explicit constitutional basis for a right to housing, with its meaning and effect determined through constitutional law and interpretation.',
        'context': 'The Bill is presented in response to the housing crisis and seeks to give housing an express place in the Constitution.',
        'issues': 'Second Stage can test the wording of the proposed right, how enforceable it would be, what duties it could place on the State and how it would interact with existing constitutional rights.',
    },
    'Public Art Mural (Exempted Development) Bill 2026': {
        'what': 'Would create planning exemptions for certain public art murals where specified conditions are met.',
        'practical': 'Qualifying murals could proceed without planning permission where they have artistic or cultural merit, have the building owner’s permission and are not commercial advertising.',
        'context': 'The Bill would change planning rules that currently govern when murals and similar works require permission.',
        'issues': 'Second Stage can test the qualifying criteria, definitions of artistic or cultural merit, local oversight and how heritage or amenity concerns would be handled.',
    },
    'River Boyne Task Force Bill 2023': {
        'what': 'Would establish a River Boyne Task Force within the existing local and regional government framework, with responsibilities for the River Boyne and its catchment area.',
        'practical': 'The Task Force would coordinate specified functions relating to the Boyne catchment and could make recommendations to planning authorities on the content of development plans.',
        'context': 'The proposal is intended to create a dedicated structure for coordinating public functions and planning considerations across the River Boyne catchment.',
        'issues': 'Second Stage can test the Task Force’s membership, powers, relationship with local authorities, planning role, accountability and resourcing.',
    },
    'Taxes Consolidation (Rights of Performers and Film Workers) (Amendment) Bill 2025': {
        'what': 'Would amend the Taxes Consolidation Act 1997 so Section 481 film tax relief certification takes account of equal treatment for Irish performers.',
        'practical': 'Qualifying productions seeking Section 481 relief would have to meet requirements intended to prevent Irish performers receiving worse intellectual-property terms than international performers.',
        'context': 'The Bill follows recommendations from the Oireachtas Budgetary Oversight Committee on the operation of the Section 481 industry-development test.',
        'issues': 'Second Stage can test how equal treatment would be defined, how compliance would be certified and enforced, and the effect on performers and film-production companies.',
    },
}
base.MANUAL.update(EXTRA_MANUAL)

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
    re.compile(r'(?i)^purpose of the bill\b'),
    re.compile(r'(?i)^of (?:this )?bill\b'),
    re.compile(r'(?i)^no\.\s*\d+\s+of\s+\d{4}\b'),
    re.compile(r'(?i)\bfeabhra\s*,?\s*20\d{2}\b'),
]
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
    if s.count('(') != s.count(')'):
        return True
    if s.count('“') != s.count('”'):
        return True
    if re.search(r'(?:^|\s)[1-9]\.$', s):
        return True
    if re.search(r'(?i)\b(?:in|of|to|and|or|with|for|on|the)\.$', s):
        return True
    if re.search(r'(?i)(?:following|things|measures|changes|provisions|objectives)\s*:\s*(?:[1-9][.)]?)?\s*$', s):
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

    what_src = lt or purpose or choose(pool, ('purpose', 'would ', 'will ', 'seeks to', 'provide for', 'amend', 'establish', 'prohibit', 'require'), used)
    if what_src:
        used.add(what_src); what = base.shorten(what_src, 300)
    else:
        what = f'The Bill proposes a legal change in the area described by its title: {title}.'

    practical_src = choose(pool, ('would ', 'will ', 'require', 'allow', 'permit', 'entitle', 'provide', 'establish', 'prohibit', 'remove', 'extend', 'reduce', 'increase'), used)
    if practical_src:
        used.add(practical_src); practical = base.shorten(practical_src, 300)
    elif lt:
        practical = base.shorten(lt, 300)
    else:
        practical = 'The detailed legal effect is set out in the official Bill text.'

    context_src = choose(pool, ('background', 'respond', 'intended', 'aim', 'currently', 'existing', 'because', 'following', 'recommendation', 'concern'), used)
    if context_src:
        context = base.shorten(context_src, 300)
    elif purpose and base.clean_text(purpose).lower() != base.clean_text(what).lower():
        context = base.shorten(purpose, 300)
    else:
        context = f'{sponsor} sponsors the Bill. The official Bill text sets out the proposed legal change; no wider political support is inferred from sponsorship.'

    issues = base.issues_from(text)
    result = {'what':what,'practical':practical,'context':context,'issues':issues,'confidence':'high' if len(text)>700 and (lt or purpose) else 'medium','extracted_chars':len(text)}
    bad = [field for field in ('what','practical','context','issues') if contaminated(result[field])]
    if bad:
        if 'what' in bad: result['what'] = f'The Bill proposes a legal change in the area described by its title: {title}.'
        if 'practical' in bad: result['practical'] = 'The detailed legal effect is set out in the official Bill text.'
        if 'context' in bad: result['context'] = f'{sponsor} sponsors the Bill. The official record does not provide a clean plain-English background summary in the extracted source text.'
        if 'issues' in bad: result['issues'] = 'Second Stage can test the Bill’s overall approach, including its scope, implementation and safeguards.'
        result['confidence'] = 'medium'
    for field in ('what','practical','context','issues'):
        if contaminated(result[field]):
            raise RuntimeError(f'public copy still contaminated after fallback: {title} / {field} / {result[field]}')
    return result


base.build_copy = safe_build_copy
base.main()

out = json.loads((base.OUT / 'copy.json').read_text(encoding='utf-8'))
failures=[]
for row in out.get('rows',[]):
    is_manual=row.get('confidence')=='manual'
    for field in ('what','practical','context','issues'):
        value=str(row.get(field,'') or '')
        if contaminated(value,manual=is_manual): failures.append({'title':row.get('title'),'field':field,'text':value})
(base.OUT / 'public_copy_gate.json').write_text(json.dumps({'failure_count':len(failures),'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
if failures: raise SystemExit(f'public-copy contamination gate failed for {len(failures)} fields')
print('public-copy contamination gate passed: 0 contaminated fields')
