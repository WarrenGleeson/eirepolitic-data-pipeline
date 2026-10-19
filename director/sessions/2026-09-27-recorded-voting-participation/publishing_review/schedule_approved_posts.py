"""Schedule three user-approved recorded-voting Instagram carousels exactly once.

The review manifest, image files and captions are immutable inputs. Check live
DynamoDB and EventBridge state before uploading assets or scheduling anything.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from publishing.scheduler import EventBridgePublicationScheduler, SchedulerTarget
from publishing.standard_pipeline import prepare_standard_publication

SESSION_ROOT = Path('director/sessions/2026-09-27-recorded-voting-participation')
# Compact IDs are required: EventBridge Scheduler names cannot exceed 64 chars.
PERIOD_KEY = '20260406-20261006'
FACTORY_RUN_ID = '20261020'

CAPTIONS = {
    'tds': """How often did TDs have a recorded vote or formal abstention when they were eligible to participate in a Dáil division?

This post looks at recorded voting participation across individual TDs over the six-month review period, including those with a recorded participation rate of 100%, the highest rates below 100%, and the lowest rates.

Swipe through for the figures, how the metric is calculated, and the important limitations behind the data.

Recorded voting participation does not by itself measure a TD’s attendance, workload, effectiveness, or overall job performance.

#EirePolitic #Oireachtas #IrishPolitics #DáilÉireann #TDs""",
    'constituencies': """How did recorded voting participation compare across Dáil constituencies?

This post combines the eligible voting opportunities of TDs within each constituency and shows the constituencies with the highest and lowest recorded-participation percentages during the review period.

Swipe through for the figures, how the constituency percentages are calculated, and the methodology behind the comparison.

Recorded voting participation does not by itself measure a TD’s attendance, workload, effectiveness, or overall job performance.

#EirePolitic #Oireachtas #IrishPolitics #DáilÉireann #Constituencies""",
    'parties': """How did recorded voting participation compare across parties and parliamentary groups?

This post combines the eligible voting opportunities of TDs by their party or group at the time of each division and shows the highest and lowest recorded-participation percentages during the review period.

Swipe through for the figures, how the percentages are calculated, and the methodology behind the comparison.

Recorded voting participation does not by itself measure a TD’s attendance, workload, effectiveness, or overall job performance.

#EirePolitic #Oireachtas #IrishPolitics #DáilÉireann #IrishPoliticsData""",
}

PLAN = (
    ('tds', 'TDs', '2026-10-20T15:00:00'),
    ('constituencies', 'Constituencies', '2026-10-21T15:00:00'),
    ('parties', 'Parties', '2026-10-22T15:00:00'),
)


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _project_id(key: str) -> str:
    return 'rvp-' + key


def _publication_id(key: str) -> str:
    # Must match publishing.standard_pipeline._slug and its identity construction.
    return f'ig-{_project_id(key)}-{PERIOD_KEY}-{FACTORY_RUN_ID}'


def _schedule_name(key: str) -> str:
    name = f'instagram-{_publication_id(key)}-v1'
    if len(name) > 64:
        raise RuntimeError(f'EventBridge schedule name exceeds 64 characters: {name}')
    return name


def _check_manifest(repo: Path) -> dict:
    manifest = json.loads((repo / SESSION_ROOT / 'split_posts_review/manifest.json').read_text(encoding='utf-8'))
    if manifest.get('status') != 'PASS' or manifest.get('computer_visual_qa', {}).get('pass') is not True:
        raise RuntimeError('Approved slide QA manifest is not PASS')
    if manifest.get('publication_enabled') is not False or manifest.get('review_only') is not True:
        raise RuntimeError('Expected review-only manifest guard is missing')
    if 'Verona Murphy' not in manifest.get('td_exclusions', []):
        raise RuntimeError('Expected presiding-officer exclusion is missing')
    if manifest.get('period', {}).get('start') != '2026-04-06' or manifest.get('period', {}).get('end') != '2026-10-06':
        raise RuntimeError('Unexpected data review period')
    posts = {p['kind']: p for p in manifest['posts']}
    if set(posts) != {kind for _, kind, _ in PLAN}:
        raise RuntimeError('Expected exactly three approved carousel posts')
    for key, kind, _ in PLAN:
        paths = posts[kind]['slides']
        if len(paths) != (5 if key == 'tds' else 4):
            raise RuntimeError(f'Unexpected slide count: {kind}')
        for path in paths:
            src = (repo / path).resolve()
            if repo.resolve() not in src.parents or not src.is_file():
                raise RuntimeError(f'Missing or invalid approved slide: {path}')
        _schedule_name(key)
    return posts


def _ledger_items(table) -> list[dict]:
    rows = []
    scan_args = {}
    while True:
        page = table.scan(**scan_args)
        rows.extend(row for row in page.get('Items', []) if row.get('entity_type') == 'publication_control')
        last_key = page.get('LastEvaluatedKey')
        if not last_key:
            return rows
        scan_args['ExclusiveStartKey'] = last_key


def _preflight(items: list[dict], scheduler_client) -> None:
    now = datetime.now(timezone.utc)
    expected = {key: _as_utc(when) for key, _, when in PLAN}
    if any(when <= now for when in expected.values()):
        raise RuntimeError('A requested slot is in the past; refusing to reschedule silently')

    # Check all active control records, including the earlier long-ID attempt.
    for item in items:
        if item.get('state') in {'cancelled', 'failed'}:
            continue
        publication_id = item.get('publication_id', '')
        request = item.get('request') or {}
        project = request.get('project_id', '')
        schedule = item.get('schedule') or {}
        existing = item.get('scheduled_at_utc') or schedule.get('scheduled_at_utc')
        for key, _, _ in PLAN:
            planned = expected[key]
            ours = _publication_id(key)
            legacy = 'recorded_voting_participation_' + key
            if (project in {_project_id(key), legacy} or publication_id == ours) and item.get('state') in {'scheduled', 'published'}:
                if publication_id != ours or not existing or _as_utc(existing) != planned or item.get('state') == 'published':
                    raise RuntimeError(f'Existing publication for {key} needs manual review: {publication_id}')
            if existing and _as_utc(existing) == planned:
                if publication_id != ours or item.get('state') != 'scheduled':
                    raise RuntimeError(f'15:00 UTC slot occupied by {publication_id} ({item.get("state")})')

    # EventBridge schedule state can outlive/precede a ledger record after a partial failure.
    for key, _, when in PLAN:
        name = _schedule_name(key)
        try:
            existing = scheduler_client.get_schedule(Name=name, GroupName='eirepolitic-instagram')
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ResourceNotFoundException':
                continue
            raise
        expected_expression = 'at(' + when + ')'
        expected_input = json.dumps({'expected_version': 1, 'publication_id': _publication_id(key)}, separators=(',', ':'), sort_keys=True)
        if existing.get('ScheduleExpression') != expected_expression or (existing.get('Target') or {}).get('Input') != expected_input:
            raise RuntimeError(f'Existing EventBridge schedule has unexpected details: {name}')
        if not any(row.get('publication_id') == _publication_id(key) and row.get('state') == 'scheduled' for row in items):
            raise RuntimeError(f'Orphan EventBridge schedule requires manual review: {name}')
    print('PASS: live DynamoDB and EventBridge collision preflight for all three slots', flush=True)


def _prepare_artifacts(repo: Path, posts: dict, key: str, kind: str) -> Path:
    root = repo / 'artifacts' / 'director-recorded-voting-publish' / key
    root.mkdir(parents=True, exist_ok=True)
    for index, src in enumerate(posts[kind]['slides'], start=1):
        shutil.copy2(repo / src, root / f'{index:02d}.png')
    (root / 'caption.txt').write_text(CAPTIONS[key].strip() + '\n', encoding='utf-8')
    handoff = {
        'schema_version': 1,
        'project_id': _project_id(key),
        'period_key': PERIOD_KEY,
        'qa_all_passed': True,
        'factory_publication_enabled': False,
        'slides': [{'path': f'{index:02d}.png'} for index in range(1, len(posts[kind]['slides']) + 1)],
        'caption_path': 'caption.txt',
    }
    (root / 'publication_handoff.json').write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return root


def main() -> None:
    repo = Path.cwd()
    posts = _check_manifest(repo)
    for name in ('BUCKET', 'FUNCTION_ARN', 'ROLE_ARN', 'DLQ_ARN'):
        if not os.environ.get(name) or os.environ[name] == 'None':
            raise RuntimeError(f'Missing required AWS resource: {name}')

    db = boto3.resource('dynamodb', region_name='us-east-2')
    table = db.Table('eirepolitic-publications')
    scheduler_client = boto3.client('scheduler', region_name='us-east-2')
    _preflight(_ledger_items(table), scheduler_client)  # No writes before this completes.

    s3 = boto3.client('s3', region_name='us-east-2')
    target = SchedulerTarget(
        lambda_arn=os.environ['FUNCTION_ARN'],
        role_arn=os.environ['ROLE_ARN'],
        dlq_arn=os.environ['DLQ_ARN'],
    )
    results = []
    for key, kind, when in PLAN:
        root = _prepare_artifacts(repo, posts, key, kind)
        result = prepare_standard_publication(
            artifact_root=root,
            factory_run_id=FACTORY_RUN_ID,
            approved_by='warrengleeson',
            mode='scheduled',
            bucket=os.environ['BUCKET'],
            dynamodb_resource=db,
            s3_client=s3,
            scheduler_client=scheduler_client,
            scheduler_target=target,
            scheduled_local=when,
            timezone_name='UTC',
        )
        if result.publication_id != _publication_id(key) or result.schedule_name != _schedule_name(key):
            raise RuntimeError(f'Unexpected publication/schedule identity for {kind}')
        if result.state != 'scheduled' or not result.scheduled_at_utc or _as_utc(result.scheduled_at_utc) != _as_utc(when):
            raise RuntimeError(f'Unexpected schedule verification result for {kind}')
        row = asdict(result)
        row['kind'] = kind
        row['scheduled_local'] = when
        row['timezone'] = 'UTC'
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    receipt = repo / SESSION_ROOT / 'publishing_review/recorded_voting_scheduled_publications.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({'status': 'PASS', 'publications': results}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Verified {len(results)} scheduled carousels; receipt: {receipt}', flush=True)


if __name__ == '__main__':
    main()
