from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

from instagram_insights.meta_client import MetaInsightsClient, first_metric_value


DEFAULT_ACCOUNT_METRICS: Tuple[str, ...] = (
    "reach",
    "views",
    "accounts_engaged",
    "total_interactions",
    "likes",
    "comments",
    "saves",
    "shares",
    "reposts",
)

DEFAULT_MEDIA_METRICS: Tuple[str, ...] = (
    "reach",
    "views",
    "likes",
    "comments",
    "saved",
    "shares",
    "reposts",
    "total_interactions",
)


@dataclass(frozen=True)
class PublishedMedia:
    publication_id: str
    publication_version: int
    project_id: str
    period: str
    media_id: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scan_all(table: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    kwargs: Dict[str, Any] = {}
    while True:
        response = table.scan(**kwargs)
        items.extend(response.get("Items", []))
        key = response.get("LastEvaluatedKey")
        if not key:
            return items
        kwargs["ExclusiveStartKey"] = key


def list_published_media(publication_table: Any) -> List[PublishedMedia]:
    items = _scan_all(publication_table)
    controls: Dict[Tuple[str, int], Dict[str, Any]] = {}
    executions: Dict[Tuple[str, int], str] = {}

    for item in items:
        entity_type = item.get("entity_type")
        if entity_type == "publication_control":
            request = item.get("request") or {}
            publication_id = str(item.get("publication_id") or request.get("publication_id") or "")
            version = int(item.get("publication_version") or request.get("publication_version") or 0)
            if publication_id and version:
                controls[(publication_id, version)] = item
        elif entity_type == "execution_attempt":
            attempt = item.get("attempt") or {}
            publication_id = str(item.get("publication_id") or attempt.get("publication_id") or "")
            version = int(item.get("publication_version") or attempt.get("publication_version") or 0)
            media_id = attempt.get("published_media_id")
            if publication_id and version and media_id:
                executions[(publication_id, version)] = str(media_id)

    published: List[PublishedMedia] = []
    for key, media_id in executions.items():
        control = controls.get(key)
        if not control:
            continue
        request = control.get("request") or {}
        published.append(
            PublishedMedia(
                publication_id=key[0],
                publication_version=key[1],
                project_id=str(request.get("project_id") or ""),
                period=str(request.get("period") or ""),
                media_id=media_id,
            )
        )
    return published


def _safe_error(error: Dict[str, Any] | None) -> Dict[str, Any]:
    error = error or {}
    return {
        "code": error.get("code"),
        "type": error.get("type"),
        "message": error.get("message"),
        "error_subcode": error.get("error_subcode"),
    }


def _write_metric_snapshot(
    analytics_table: Any,
    *,
    subject_key: str,
    snapshot_at: str,
    metric: str,
    value: Any = None,
    error: Dict[str, Any] | None = None,
    dimensions: Dict[str, Any] | None = None,
) -> None:
    item: Dict[str, Any] = {
        "pk": subject_key,
        "sk": f"SNAP#{snapshot_at}#METRIC#{metric}",
        "entity_type": "instagram_insight_snapshot",
        "snapshot_at_utc": snapshot_at,
        "metric": metric,
        "status": "ok" if error is None else "unsupported_or_error",
    }
    if value is not None:
        item["value"] = value
    if error is not None:
        item["error"] = _safe_error(error)
    if dimensions:
        item.update(dimensions)
    analytics_table.put_item(Item=item)


def collect_account_metrics(
    analytics_table: Any,
    client: MetaInsightsClient,
    *,
    instagram_account_id: str,
    snapshot_at: str,
    metrics: Iterable[str] = DEFAULT_ACCOUNT_METRICS,
) -> Dict[str, str]:
    statuses: Dict[str, str] = {}
    for metric in metrics:
        response = client.account_insight(instagram_account_id, metric)
        if response.ok:
            _write_metric_snapshot(
                analytics_table,
                subject_key=f"ACCOUNT#{instagram_account_id}",
                snapshot_at=snapshot_at,
                metric=metric,
                value=first_metric_value(response.data or {}),
            )
            statuses[metric] = "ok"
        else:
            _write_metric_snapshot(
                analytics_table,
                subject_key=f"ACCOUNT#{instagram_account_id}",
                snapshot_at=snapshot_at,
                metric=metric,
                error=response.error,
            )
            statuses[metric] = "unsupported_or_error"
    return statuses


def collect_media_metrics(
    analytics_table: Any,
    client: MetaInsightsClient,
    *,
    published_media: Iterable[PublishedMedia],
    snapshot_at: str,
    metrics: Iterable[str] = DEFAULT_MEDIA_METRICS,
) -> Dict[str, Dict[str, str]]:
    all_statuses: Dict[str, Dict[str, str]] = {}
    for media in published_media:
        statuses: Dict[str, str] = {}
        details_response = client.media_details(media.media_id)
        dimensions = {
            "media_id": media.media_id,
            "publication_id": media.publication_id,
            "publication_version": media.publication_version,
            "project_id": media.project_id,
            "period": media.period,
        }
        if details_response.ok:
            details = details_response.data or {}
            for field in ("media_type", "media_product_type", "timestamp", "permalink"):
                if details.get(field) is not None:
                    dimensions[field] = details[field]

        for metric in metrics:
            response = client.media_insight(media.media_id, metric)
            if response.ok:
                _write_metric_snapshot(
                    analytics_table,
                    subject_key=f"MEDIA#{media.media_id}",
                    snapshot_at=snapshot_at,
                    metric=metric,
                    value=first_metric_value(response.data or {}),
                    dimensions=dimensions,
                )
                statuses[metric] = "ok"
            else:
                _write_metric_snapshot(
                    analytics_table,
                    subject_key=f"MEDIA#{media.media_id}",
                    snapshot_at=snapshot_at,
                    metric=metric,
                    error=response.error,
                    dimensions=dimensions,
                )
                statuses[metric] = "unsupported_or_error"
        all_statuses[media.media_id] = statuses
    return all_statuses
