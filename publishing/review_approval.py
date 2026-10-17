from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

from botocore.exceptions import ClientError


class ReviewApprovalError(RuntimeError):
    pass


class ReviewApprovalConflict(ReviewApprovalError):
    pass


class ReviewApprovalNotFound(ReviewApprovalError):
    pass


@dataclass(frozen=True)
class ReviewApprovalRecord:
    review_id: str
    project_id: str
    period: str
    source_batch_id: str
    review_uri: str
    zip_name: str
    recipient: str
    sender: str
    token: str
    status: str
    created_at_utc: str
    expires_at_epoch: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def review_id(*, project_id: str, period: str, source_batch_id: str, review_uri: str, zip_name: str) -> str:
    payload = "\n".join((project_id, period, source_batch_id, review_uri, zip_name)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def new_token() -> str:
    return secrets.token_urlsafe(18)


def _review_key(value: str) -> dict[str, str]:
    return {"pk": f"REVIEW#{value}", "sk": "CONTROL"}


def approval_registry_keys(*, prefix: str, token: str, project_id: str, period: str, review_id_value: str) -> dict[str, str]:
    root = prefix.strip("/")
    safe_project = quote(project_id, safe="-_.")
    safe_period = quote(period, safe="-_.")
    return {
        "token": f"{root}/tokens/{token}.json",
        "review": f"{root}/reviews/{review_id_value}.json",
        "latest": f"{root}/latest/{safe_project}/{safe_period}.json",
    }


def register_review_s3(
    *,
    s3: Any,
    bucket: str,
    prefix: str,
    project_id: str,
    period: str,
    source_batch_id: str,
    review_uri: str,
    zip_name: str,
    recipient: str,
    sender: str,
    token_ttl_days: int = 14,
    now: datetime | None = None,
) -> ReviewApprovalRecord:
    current = now or utc_now()
    created = current.isoformat(timespec="seconds").replace("+00:00", "Z")
    expires = int((current + timedelta(days=token_ttl_days)).timestamp())
    value = review_id(
        project_id=project_id,
        period=period,
        source_batch_id=source_batch_id,
        review_uri=review_uri,
        zip_name=zip_name,
    )
    token = new_token()
    keys = approval_registry_keys(
        prefix=prefix,
        token=token,
        project_id=project_id,
        period=period,
        review_id_value=value,
    )
    review_payload = {
        "schema_version": 1,
        "review_id": value,
        "project_id": project_id,
        "period": period,
        "source_batch_id": source_batch_id,
        "review_uri": review_uri,
        "zip_name": zip_name,
        "recipient": recipient,
        "sender": sender,
        "status": "pending_human_review",
        "created_at_utc": created,
        "expires_at_epoch": expires,
    }
    token_payload = {
        "schema_version": 1,
        "token": token,
        "review_id": value,
        "project_id": project_id,
        "period": period,
        "expires_at_epoch": expires,
        "review_key": keys["review"],
    }
    latest_payload = {
        "schema_version": 1,
        "project_id": project_id,
        "period": period,
        "review_id": value,
        "updated_at_utc": created,
    }
    for key, payload in (
        (keys["review"], review_payload),
        (keys["token"], token_payload),
        (keys["latest"], latest_payload),
    ):
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
    return ReviewApprovalRecord(
        review_id=value,
        project_id=project_id,
        period=period,
        source_batch_id=source_batch_id,
        review_uri=review_uri,
        zip_name=zip_name,
        recipient=recipient,
        sender=sender,
        token=token,
        status="pending_human_review",
        created_at_utc=created,
        expires_at_epoch=expires,
    )


def resolve_token_s3(
    *,
    s3: Any,
    bucket: str,
    prefix: str,
    token: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = prefix.strip("/")
    token_key = f"{root}/tokens/{token}.json"
    try:
        token_payload = json.loads(s3.get_object(Bucket=bucket, Key=token_key)["Body"].read())
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            raise ReviewApprovalNotFound("approval token was not found") from exc
        raise
    current_epoch = int((now or utc_now()).timestamp())
    if int(token_payload.get("expires_at_epoch") or 0) < current_epoch:
        raise ReviewApprovalConflict("approval token has expired")
    review_key = str(token_payload.get("review_key") or "")
    if not review_key:
        raise ReviewApprovalNotFound("approval token does not reference a review package")
    review = json.loads(s3.get_object(Bucket=bucket, Key=review_key)["Body"].read())
    keys = approval_registry_keys(
        prefix=prefix,
        token=token,
        project_id=str(review["project_id"]),
        period=str(review["period"]),
        review_id_value=str(review["review_id"]),
    )
    latest = json.loads(s3.get_object(Bucket=bucket, Key=keys["latest"])["Body"].read())
    if str(latest.get("review_id")) != str(review["review_id"]):
        raise ReviewApprovalConflict("this review email has been superseded by a newer review package")
    return review


def ensure_review_control(*, table: Any, review: dict[str, Any]) -> dict[str, Any]:
    item = {
        **_review_key(str(review["review_id"])),
        "entity_type": "instagram_review_approval",
        "review_id": str(review["review_id"]),
        "project_id": str(review["project_id"]),
        "period": str(review["period"]),
        "source_batch_id": str(review["source_batch_id"]),
        "review_uri": str(review["review_uri"]),
        "zip_name": str(review["zip_name"]),
        "recipient": str(review["recipient"]),
        "sender": str(review["sender"]),
        "status": "pending_human_review",
        "created_at_utc": str(review["created_at_utc"]),
        "expires_at_epoch": int(review["expires_at_epoch"]),
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return item
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    existing = table.get_item(Key=_review_key(str(review["review_id"])), ConsistentRead=True).get("Item")
    if not existing:
        raise ReviewApprovalNotFound("review control record disappeared during creation")
    return existing


def acquire_review(*, table: Any, review_id_value: str, approved_by: str, now: datetime | None = None) -> dict[str, Any]:
    approved_at = (now or utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        response = table.update_item(
            Key=_review_key(review_id_value),
            UpdateExpression="SET #status = :processing, approved_by = :approved_by, approved_at_utc = :approved_at",
            ConditionExpression="#status = :pending",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":pending": "pending_human_review",
                ":processing": "processing_approval",
                ":approved_by": approved_by,
                ":approved_at": approved_at,
            },
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    current = table.get_item(Key=_review_key(review_id_value), ConsistentRead=True).get("Item")
    if not current:
        raise ReviewApprovalNotFound("review package was not found")
    status = str(current.get("status") or "")
    if status in {"processing_approval", "scheduled"}:
        return current
    raise ReviewApprovalConflict(f"review package is not approvable in state {status!r}")


def ensure_schedule_plan(*, table: Any, review_id_value: str, proposed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    response = table.update_item(
        Key=_review_key(review_id_value),
        UpdateExpression="SET schedule_plan = if_not_exists(schedule_plan, :plan)",
        ConditionExpression="attribute_exists(pk)",
        ExpressionAttributeValues={":plan": proposed_rows},
        ReturnValues="ALL_NEW",
    )
    return list(response["Attributes"].get("schedule_plan") or [])


def mark_scheduled(*, table: Any, review_id_value: str, schedule_rows: list[dict[str, Any]]) -> dict[str, Any]:
    response = table.update_item(
        Key=_review_key(review_id_value),
        UpdateExpression="SET #status = :scheduled, scheduled_publications = :rows, scheduled_at_utc = :now",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":scheduled": "scheduled",
            ":rows": schedule_rows,
            ":now": utc_now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        },
        ReturnValues="ALL_NEW",
    )
    return response["Attributes"]


def parse_approval_command(text: str) -> bool:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        return line.casefold() == "approved"
    return False


def next_free_daily_slots(
    *,
    scheduled_at_utc_values: Iterable[str],
    count: int,
    hour_utc: int = 8,
    now: datetime | None = None,
    minimum_lead_minutes: int = 30,
) -> list[datetime]:
    if count < 1:
        return []
    current = (now or utc_now()).astimezone(timezone.utc)
    occupied: set[str] = set()
    for value in scheduled_at_utc_values:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue
        occupied.add(dt.isoformat(timespec="seconds"))

    candidate = current.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if candidate <= current + timedelta(minutes=minimum_lead_minutes):
        candidate += timedelta(days=1)

    slots: list[datetime] = []
    while len(slots) < count:
        if candidate.isoformat(timespec="seconds") not in occupied:
            slots.append(candidate)
        candidate += timedelta(days=1)
    return slots


def display_period(period: str) -> str:
    try:
        year, month = str(period).split("-", 1)
        return datetime(int(year), int(month), 1).strftime("%B %Y")
    except Exception:
        return str(period)


def standard_party_caption(*, party: str, period: str) -> str:
    return (
        f"Our Party Speech Breakdown looks at the issues discussed by {party} in Dáil speeches during {display_period(period)}.\n\n"
        "Swipe through to see:\n\n"
        "• their most discussed issues\n"
        "• the issues they discussed more than the average across parties\n"
        "• the issues they discussed more than average per TD\n\n"
        "These figures measure how often issues were discussed, not the party’s position on them.\n\n"
        "#EirePolitic #Oireachtas #IrishPolitics #DáilÉireann #PoliticalData"
    )
