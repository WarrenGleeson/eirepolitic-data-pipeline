from __future__ import annotations

import json
import os
from typing import Any, Dict

import boto3

from instagram_insights.collector import (
    collect_account_metrics,
    collect_media_metrics,
    list_published_media,
    select_checkpoint_media,
    utc_now_iso,
)
from instagram_insights.meta_client import MetaInsightsClient


def _load_secret(secret_name: str) -> Dict[str, Any]:
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def lambda_handler(event: Dict[str, Any] | None, context: Any) -> Dict[str, Any]:
    event = event or {}
    secret_name = os.environ["INSTAGRAM_SECRET_NAME"]
    publication_table_name = os.environ["PUBLICATION_TABLE_NAME"]
    analytics_table_name = os.environ["ANALYTICS_TABLE_NAME"]
    api_version = os.environ.get("META_API_VERSION", "v25.0")

    secret = _load_secret(secret_name)
    access_token = secret["page_access_token"]
    instagram_account_id = str(secret["instagram_account_id"])

    dynamodb = boto3.resource("dynamodb")
    publication_table = dynamodb.Table(publication_table_name)
    analytics_table = dynamodb.Table(analytics_table_name)
    client = MetaInsightsClient(access_token, api_version=api_version)

    canary_mode = event.get("source") == "manual-canary"
    account_metrics = ("reach",) if canary_mode else None
    media_metrics = ("reach",) if canary_mode else None

    snapshot_at = utc_now_iso()
    account_kwargs: Dict[str, Any] = {
        "instagram_account_id": instagram_account_id,
        "snapshot_at": snapshot_at,
    }
    if account_metrics is not None:
        account_kwargs["metrics"] = account_metrics
    account_status = collect_account_metrics(
        analytics_table,
        client,
        **account_kwargs,
    )

    published_media = list_published_media(publication_table)
    if canary_mode:
        selected_media = published_media[:1]
    else:
        selected_media = select_checkpoint_media(published_media)

    media_kwargs: Dict[str, Any] = {
        "published_media": selected_media,
        "snapshot_at": snapshot_at,
    }
    if media_metrics is not None:
        media_kwargs["metrics"] = media_metrics
    media_status = collect_media_metrics(
        analytics_table,
        client,
        **media_kwargs,
    )

    account_ok = sum(1 for status in account_status.values() if status == "ok")
    media_metric_ok = sum(
        1
        for statuses in media_status.values()
        for status in statuses.values()
        if status == "ok"
    )

    return {
        "ok": account_ok > 0,
        "mode": "canary" if canary_mode else "scheduled",
        "snapshot_at_utc": snapshot_at,
        "instagram_account_id": instagram_account_id,
        "account_metrics_ok": account_ok,
        "account_metrics_total": len(account_status),
        "published_media_available": len(published_media),
        "published_media_selected": len(selected_media),
        "media_metrics_ok": media_metric_ok,
        "media_metric_attempts": sum(len(statuses) for statuses in media_status.values()),
    }
