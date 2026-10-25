"""Rebook approved recorded-voting carousels after October 20 partial failure.

Uses immutable captions/slides/QA from schedule_approved_posts. No deletion or
modification of the stale historical record; generates fresh publication IDs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import boto3

import schedule_approved_posts as original

original.FACTORY_RUN_ID = '20261026'
original.PLAN = (
    ('tds', 'TDs', '2026-10-26T15:00:00'),
    ('constituencies', 'Constituencies', '2026-10-27T15:00:00'),
    ('parties', 'Parties', '2026-10-28T15:00:00'),
)

OLD_TD_ID = 'ig-rvp-tds-20260406-20261006-20261020'


def _preflight(items: list[dict], scheduler_client) -> None:
    now = datetime.now(timezone.utc)
    slots = {key: original._as_utc(when) for key, _, when in original.PLAN}
    if any(slot <= now for slot in slots.values()):
        raise RuntimeError('New slots must be in the future')

    # Scan all known EventBridge schedules, not just intended names.
    schedules = []
    cursor = {}
    while True:
        page = scheduler_client.list_schedules(GroupName='eirepolitic-instagram', **cursor)
        schedules.extend(page.get('Schedules', []))
        if not page.get('NextToken'):
            break
        cursor = {'NextToken': page['NextToken']}

    for key, _, when in original.PLAN:
        expected_id = original._publication_id(key)
        expected_name = original._schedule_name(key)
        target_time = slots[key]
        for row in items:
            if row.get('state') in ('failed', 'cancelled'):
                continue
            row_id = str(row.get('publication_id', ''))
            project = str((row.get('request') or {}).get('project_id', ''))
            existing_time = (row.get('schedule') or {}).get('scheduled_at_utc') or row.get('scheduled_at_utc')
            parsed = original._as_utc(str(existing_time)) if existing_time else None
            if parsed == target_time and row_id != expected_id:
                raise RuntimeError(f'Publication collision at {when}: {row_id}')
            if row_id == expected_id:
                if row.get('state') != 'scheduled' or parsed != target_time:
                    raise RuntimeError(f'Unexpected existing target publication state: {row_id}')
                continue  # Valid retry will verify same schedule.
            if project in {original._project_id(key), 'recorded_voting_participation_'+key}:
                # Only allowed legacy record is proven stale TDs from Oct 20.
                if row_id == OLD_TD_ID and row.get('state') == 'scheduled' and parsed == original._as_utc('2026-10-20T15:00:00'):
                    continue
                raise RuntimeError(f'Other existing publication requires review: {row_id}')

        for item in schedules:
            if item.get('State') == 'DISABLED':
                continue
            if item.get('ScheduleExpression') == f'at({when})' and item.get('Name') != expected_name:
                raise RuntimeError(f'EventBridge slot collision: {when} ({item["Name"]})')
            if item.get('Name') == expected_name and item.get('ScheduleExpression') != f'at({when})':
                raise RuntimeError(f'Unexpected existing EventBridge target: {expected_name}')

    if any(row.get('Name') == f'instagram-{OLD_TD_ID}-v1' for row in schedules):
        raise RuntimeError('Legacy TDs EventBridge schedule exists; stop before double publication')
    print('PASS: legacy TDs is orphaned; replacement slots are available', flush=True)


original._preflight = _preflight

if __name__ == '__main__':
    original.main()
