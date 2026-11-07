"""Safely re-schedule only the failed TDs carousel using the approved artifacts.

Read-only duplicate checks precede all writes. The expired/uncertain October
attempt is retained without modification. No other carousels are touched.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from urllib import error, parse, request

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import schedule_approved_posts as approved
from publishing.scheduler import SchedulerTarget
from publishing.standard_pipeline import prepare_standard_publication

OLD_PUBLICATION_ID = 'ig-rvp-tds-20260406-20261006-20261026'
RECOVERY_RUN_ID = '20261107'
NEW_PUBLICATION_ID = f'ig-rvp-tds-{approved.PERIOD_KEY}-{RECOVERY_RUN_ID}'
SCHEDULE_NAME = f'instagram-{NEW_PUBLICATION_ID}-v1'
GROUP = 'eirepolitic-instagram'
REGION = 'us-east-2'
RECEIPT = approved.SESSION_ROOT / 'publishing_review/tds_recovery_scheduled_20261107.json'


def _get_schedule(scheduler, name: str):
    try:
        return scheduler.get_schedule(Name=name, GroupName=GROUP)
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'ResourceNotFoundException':
            return None
        raise


def _all_schedules(scheduler):
    result, kwargs = [], {}
    while True:
        response = scheduler.list_schedules(GroupName=GROUP, **kwargs)
        result.extend(response.get('Schedules', []))
        if not response.get('NextToken'):
            return result
        kwargs = {'NextToken': response['NextToken']}


def _check_meta(account_secret, caption: str):
    # A previously ambiguous media_publish request must never be retried blindly.
    credentials = json.loads(account_secret.get_secret_value(SecretId='eirepolitic/instagram/publishing')['SecretString'])
    account = str(credentials['instagram_account_id'])
    token = credentials['page_access_token']
    old_parent = '17903502306602427'

    def graph(path, params):
        url = 'https://graph.facebook.com/v25.0/' + path + '?' + parse.urlencode(params)
        req = request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}, method='GET')
        try:
            with request.urlopen(req, timeout=30) as response:
                return json.loads(response.read())
        except error.HTTPError as exc:
            # Errors must stop the recovery; do not assume absence of a post.
            raise RuntimeError(f'Meta verification failed: HTTP {exc.code}') from None

    container = graph(old_parent, {'fields': 'id,status_code'})
    if container.get('status_code') != 'EXPIRED':
        raise RuntimeError('Old TDs container is not verified expired; refusing a duplicate attempt')
    after = None
    checked = 0
    for _ in range(12):
        params = {'fields': 'id,caption,timestamp,permalink', 'limit': '100'}
        if after:
            params['after'] = after
        page = graph(account + '/media', params)
        media = page.get('data', [])
        checked += len(media)
        for item in media:
            if (item.get('caption') or '').strip() == caption.strip():
                raise RuntimeError(f'TDs post already exists on Instagram (media ID {item.get("id")}); no repost')
        paging = page.get('paging') or {}
        next_cursor = (paging.get('cursors') or {}).get('after')
        if not paging.get('next'):
            print(f'PASS: {checked} Instagram media checked, no existing TDs caption; old container EXPIRED', flush=True)
            return checked
        if not next_cursor or next_cursor == after:
            raise RuntimeError('Instagram media pagination incomplete; refusing duplicate risk')
        after = next_cursor
    raise RuntimeError('Instagram media history exceeded audit page cap; refusing duplicate risk')


def _slot_is_busy(slot: datetime, rows: list[dict], schedules: list[dict]):
    for row in rows:
        if row.get('state') in {'cancelled', 'failed'}:
            continue
        schedule = row.get('schedule') or {}
        existing = row.get('scheduled_at_utc') or schedule.get('scheduled_at_utc')
        if existing and approved._as_utc(str(existing)) == slot:
            return True
    expression = 'at(' + slot.strftime('%Y-%m-%dT%H:%M:%S') + ')'
    return any(s.get('State') != 'DISABLED' and s.get('ScheduleExpression') == expression for s in schedules)


def _choose_slot(now: datetime, rows: list[dict], schedules: list[dict]):
    # Existing Eirepolitic voting cadence is 15:00 UTC; start with the next day.
    for offset in range(1, 31):
        day = now.date() + timedelta(days=offset)
        slot = datetime.combine(day, time(15, 0), tzinfo=timezone.utc)
        if slot > now + timedelta(hours=2) and not _slot_is_busy(slot, rows, schedules):
            return slot
    raise RuntimeError('No available 15:00 UTC slot found in the next 30 days')


def main():
    if len(SCHEDULE_NAME) > 64:
        raise RuntimeError('EventBridge schedule name too long')
    repo = Path.cwd()
    posts = approved._check_manifest(repo)
    for field in ('BUCKET', 'FUNCTION_ARN', 'ROLE_ARN', 'DLQ_ARN'):
        if not os.getenv(field) or os.environ[field] == 'None':
            raise RuntimeError(f'Missing AWS resource {field}')
    db = boto3.resource('dynamodb', region_name=REGION)
    table = db.Table('eirepolitic-publications')
    eb = boto3.client('scheduler', region_name=REGION)
    old = table.get_item(Key={'pk': f'PUB#{OLD_PUBLICATION_ID}', 'sk': 'CONTROL'}, ConsistentRead=True).get('Item')
    attempt = table.get_item(Key={'pk': f'PUB#{OLD_PUBLICATION_ID}', 'sk': 'EXEC#v00000001'}, ConsistentRead=True).get('Item')
    if not old or old.get('state') != 'scheduled' or not attempt:
        raise RuntimeError('Old TDs control/execution changed; refusing stale recovery')
    operations = (attempt.get('attempt') or {}).get('operations', [])
    publish = next((op for op in operations if op.get('operation_key') == 'publish_parent'), None)
    if not publish or publish.get('state') != 'uncertain':
        raise RuntimeError('Old TDs publish is no longer uncertain; refusing stale recovery')
    if _get_schedule(eb, f'instagram-{OLD_PUBLICATION_ID}-v1'):
        raise RuntimeError('Old TDs EventBridge schedule still exists; refusing duplicate')

    new = table.get_item(Key={'pk': f'PUB#{NEW_PUBLICATION_ID}', 'sk': 'CONTROL'}, ConsistentRead=True).get('Item')
    all_rows = approved._ledger_items(table)
    all_schedules = _all_schedules(eb)
    existing_schedule = _get_schedule(eb, SCHEDULE_NAME)
    if new:
        scheduled = (new.get('schedule') or {}).get('scheduled_at_utc')
        if new.get('state') != 'scheduled' or not scheduled:
            raise RuntimeError('Recovery publication already exists in unexpected state; stop')
        slot = approved._as_utc(str(scheduled))
        if slot < datetime.now(timezone.utc):
            raise RuntimeError('Recovery schedule is in the past; stop')
        if existing_schedule is None:
            raise RuntimeError('Recovery ledger exists but EventBridge schedule missing; stop')
        if existing_schedule.get('ScheduleExpression') != 'at(' + slot.strftime('%Y-%m-%dT%H:%M:%S') + ')':
            raise RuntimeError('Recovery EventBridge schedule time mismatch; stop')
        if json.loads((existing_schedule.get('Target') or {}).get('Input', '{}')).get('publication_id') != NEW_PUBLICATION_ID:
            raise RuntimeError('Recovery EventBridge target mismatch; stop')
        print('PASS: recovery already scheduled; no second publishing event created', flush=True)
        result = {'publication_id': NEW_PUBLICATION_ID, 'scheduled_at_utc': slot.isoformat(), 'schedule_name': SCHEDULE_NAME, 'state': 'scheduled', 'already_scheduled': True}
    else:
        if existing_schedule:
            raise RuntimeError('Orphan recovery EventBridge schedule found; stop')
        slot = _choose_slot(datetime.now(timezone.utc), all_rows, all_schedules)
        # Race-safe preflight immediately before any mutation.
        _check_meta(boto3.client('secretsmanager', region_name=REGION), approved.CAPTIONS['tds'])
        if _slot_is_busy(slot, approved._ledger_items(table), _all_schedules(eb)):
            raise RuntimeError('Next slot was taken since initial check; stop')
        root = approved._prepare_artifacts(repo, posts, 'tds', 'TDs')
        target = SchedulerTarget(lambda_arn=os.environ['FUNCTION_ARN'], role_arn=os.environ['ROLE_ARN'], dlq_arn=os.environ['DLQ_ARN'])
        result_obj = prepare_standard_publication(
            artifact_root=root,
            factory_run_id=RECOVERY_RUN_ID,
            approved_by='warrengleeson',
            mode='scheduled',
            bucket=os.environ['BUCKET'],
            dynamodb_resource=db,
            s3_client=boto3.client('s3', region_name=REGION),
            scheduler_client=eb,
            scheduler_target=target,
            scheduled_local=slot.strftime('%Y-%m-%dT%H:%M:%S'),
            timezone_name='UTC',
        )
        if result_obj.publication_id != NEW_PUBLICATION_ID or result_obj.schedule_name != SCHEDULE_NAME or result_obj.state != 'scheduled':
            raise RuntimeError('Unexpected recovery publication identity/state')
        if approved._as_utc(str(result_obj.scheduled_at_utc)) != slot:
            raise RuntimeError('Recovery scheduled time mismatch')
        result = asdict(result_obj)
        result['already_scheduled'] = False
        print('PASS: new TDs publication scheduled and verified', flush=True)
    receipt = repo / RECEIPT
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({'status': 'PASS', 'kind': 'TDs', 'verified_at_utc': datetime.now(timezone.utc).isoformat(), 'recovery': result}, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
