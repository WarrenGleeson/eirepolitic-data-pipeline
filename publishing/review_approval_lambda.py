from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

import boto3

from publishing.review_approval import (
    acquire_review,
    display_period,
    ensure_review_control,
    ensure_schedule_plan,
    mark_scheduled,
    next_free_daily_slots,
    parse_approval_command,
    resolve_token_s3,
    standard_party_caption,
)
from publishing.schedule_inventory import list_upcoming_scheduled_publications
from publishing.scheduler import SchedulerTarget
from publishing.standard_pipeline import prepare_standard_publication

SUPPORTED_PROJECT = "party_issue_monthly_profile_v2"
_TOKEN_RE = re.compile(r"^approve\+([A-Za-z0-9_-]+)@", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value


def _s3_parts(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Expected s3:// URI, got {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/").rstrip("/")


def _extract_text(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/plain":
                try:
                    return str(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            if part.get_content_type() == "text/html":
                try:
                    value = str(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    value = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                return html_lib.unescape(_TAG_RE.sub("\n", value))
        return ""
    try:
        value = str(message.get_content())
    except Exception:
        payload = message.get_payload(decode=True) or b""
        value = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    if message.get_content_type() == "text/html":
        value = html_lib.unescape(_TAG_RE.sub("\n", value))
    return value


def _approval_token(destinations: list[str]) -> str:
    for value in destinations:
        match = _TOKEN_RE.match(str(value).strip())
        if match:
            return match.group(1)
    raise ValueError("Approval recipient token was not found")


def _safe_slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in clean.split("-") if part)


def _publication_id(project_id: str, period: str, index: int) -> str:
    return f"ig-{_safe_slug(project_id)}-{_safe_slug(period)}-p{index:02d}"


def _validate_ses_receipt(record: dict, *, approved_sender: str) -> tuple[str, str]:
    ses = record.get("ses") or {}
    mail = ses.get("mail") or {}
    receipt = ses.get("receipt") or {}
    source = str(mail.get("source") or "").strip()
    if source.casefold() != approved_sender.strip().casefold():
        raise PermissionError(f"Approval sender is not authorized: {source!r}")
    for verdict_name in ("spamVerdict", "virusVerdict"):
        status = str((receipt.get(verdict_name) or {}).get("status") or "").upper()
        if status != "PASS":
            raise PermissionError(f"SES {verdict_name} was not PASS: {status or 'missing'}")
    message_id = str(mail.get("messageId") or "").strip()
    if not message_id:
        raise ValueError("SES event is missing mail.messageId")
    token = _approval_token([str(value) for value in (receipt.get("recipients") or mail.get("destination") or [])])
    return message_id, token


def _load_reviewed_zip(review: dict, *, work_root: Path) -> Path:
    source_bucket, prefix = _s3_parts(str(review["review_uri"]))
    zip_name = str(review["zip_name"])
    local_zip = work_root / zip_name
    boto3.client("s3", region_name=os.environ.get("SOURCE_S3_REGION", "ca-central-1")).download_file(
        source_bucket,
        f"{prefix}/{zip_name}",
        str(local_zip),
    )
    extract_root = work_root / "reviewed"
    extract_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(local_zip) as archive:
        archive.extractall(extract_root)
    return extract_root


def _reviewed_parties(extract_root: Path) -> list[tuple[str, str, list[Path]]]:
    parties_root = extract_root / "parties"
    if not parties_root.is_dir():
        raise RuntimeError("Reviewed ZIP is missing parties/")
    rows: list[tuple[str, str, list[Path]]] = []
    for party_dir in parties_root.iterdir():
        if not party_dir.is_dir():
            continue
        manifest_path = party_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"Reviewed ZIP is missing party manifest: {party_dir.name}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        qa = manifest.get("qa") or {}
        if int(qa.get("failed") or 0) != 0 or int(qa.get("passed") or 0) != 5:
            raise RuntimeError(f"Reviewed party QA is not 5/5 for {party_dir.name}: {qa}")
        if manifest.get("publication_enabled") is not False:
            raise RuntimeError(f"Reviewed party publication guard is not false for {party_dir.name}")
        slides = sorted((party_dir / "slides").glob("*.png"))
        if len(slides) != 5:
            raise RuntimeError(f"Expected 5 reviewed slides for {party_dir.name}, found {len(slides)}")
        display = str(manifest.get("display_party_name") or manifest.get("party") or party_dir.name)
        rows.append((display, party_dir.name, slides))
    if not rows:
        raise RuntimeError("Reviewed ZIP contains no party packages")
    rows.sort(key=lambda row: row[0].casefold())
    return rows


def _build_party_package(*, root: Path, party_key: str, slides: list[Path], project_id: str, period: str) -> Path:
    package_root = root / party_key
    slide_entries: list[dict[str, str]] = []
    for slide in slides:
        rel = Path("slides") / slide.name
        destination = package_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(slide, destination)
        slide_entries.append({"path": str(rel).replace("\\", "/"), "party_key": party_key})
    handoff = {
        "schema_version": 1,
        "project_id": project_id,
        "period_key": period,
        "qa_all_passed": True,
        "factory_publication_enabled": False,
        "slides": slide_entries,
    }
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "publication_handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    return package_root


def _scheduler_target() -> SchedulerTarget:
    return SchedulerTarget(
        lambda_arn=_env("PUBLISHER_LAMBDA_ARN"),
        role_arn=_env("SCHEDULER_ROLE_ARN"),
        dlq_arn=_env("SCHEDULER_DLQ_ARN"),
    )


def _schedule_review(review: dict, *, approved_by: str, work_root: Path) -> list[dict]:
    project_id = str(review["project_id"])
    period = str(review["period"])
    if project_id != SUPPORTED_PROJECT:
        raise RuntimeError(f"Unsupported email-approval project: {project_id}")

    extract_root = _load_reviewed_zip(review, work_root=work_root)
    parties = _reviewed_parties(extract_root)
    dynamodb = boto3.resource("dynamodb", region_name=_env("PUBLISHING_REGION"))
    table = dynamodb.Table(_env("PUBLICATIONS_TABLE"))
    scheduler_client = boto3.client("scheduler", region_name=_env("PUBLISHING_REGION"))
    target = _scheduler_target()
    upcoming = list_upcoming_scheduled_publications(
        table=table,
        scheduler_client=scheduler_client,
        scheduler_target=target,
    )
    own_ids = {_publication_id(project_id, period, index) for index in range(1, len(parties) + 1)}
    occupied = [item.scheduled_at_utc for item in upcoming if item.publication_id not in own_ids]
    proposed_slots = next_free_daily_slots(
        scheduled_at_utc_values=occupied,
        count=len(parties),
        hour_utc=8,
    )
    proposed_plan = [
        {
            "ordinal": index,
            "party": display,
            "party_key": party_key,
            "scheduled_at_utc": slot.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        for index, ((display, party_key, _), slot) in enumerate(zip(parties, proposed_slots), start=1)
    ]
    plan = ensure_schedule_plan(
        table=table,
        review_id_value=str(review["review_id"]),
        proposed_rows=proposed_plan,
    )
    expected_keys = [party_key for _, party_key, _ in parties]
    planned_keys = [str(row.get("party_key")) for row in plan]
    if planned_keys != expected_keys:
        raise RuntimeError(f"Stored schedule plan does not match reviewed party order: {planned_keys} != {expected_keys}")

    package_root = work_root / "publication_packages"
    results: list[dict] = []
    s3_client = boto3.client("s3", region_name=_env("PUBLISHING_REGION"))
    for (display, party_key, slides), plan_row in zip(parties, plan):
        index = int(plan_row["ordinal"])
        slot = datetime.fromisoformat(str(plan_row["scheduled_at_utc"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        artifact_root = _build_party_package(
            root=package_root,
            party_key=party_key,
            slides=slides,
            project_id=project_id,
            period=period,
        )
        result = prepare_standard_publication(
            artifact_root=artifact_root,
            factory_run_id=f"p{index:02d}",
            approved_by=approved_by,
            mode="scheduled",
            bucket=_env("APPROVED_ASSETS_BUCKET"),
            dynamodb_resource=dynamodb,
            s3_client=s3_client,
            scheduler_client=scheduler_client,
            scheduler_target=target,
            scheduled_local=slot.strftime("%Y-%m-%dT%H:%M:%S"),
            timezone_name="UTC",
            caption_override=standard_party_caption(party=display, period=period),
            options_json="{}",
            table_name=_env("PUBLICATIONS_TABLE"),
        )
        results.append(
            {
                "party": display,
                "party_key": party_key,
                "publication_id": result.publication_id,
                "scheduled_at_utc": result.scheduled_at_utc,
                "schedule_name": result.schedule_name,
                "state": result.state,
            }
        )
    return results


def _send_confirmation(*, review: dict, rows: list[dict]) -> None:
    subject = f"Scheduled: Party Speech Breakdown — {display_period(str(review['period']))}"
    lines = [
        "Your reviewed Party Speech Breakdown package was approved and scheduled.",
        "",
    ]
    for row in rows:
        lines.append(f"{row['scheduled_at_utc']} — {row['party']}")
    lines.extend(["", "All times are UTC. Existing occupied 08:00 UTC slots were skipped."])
    boto3.client("sesv2", region_name=_env("SES_REGION")).send_email(
        FromEmailAddress=_env("CONFIRMATION_FROM"),
        Destination={"ToAddresses": [_env("APPROVED_REVIEWER_EMAIL")]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "\n".join(lines), "Charset": "UTF-8"}},
            }
        },
    )


def lambda_handler(event, context):
    records = event.get("Records") or []
    if len(records) != 1:
        raise ValueError(f"Expected exactly one SES record, got {len(records)}")
    record = records[0]
    message_id, token = _validate_ses_receipt(record, approved_sender=_env("APPROVED_REVIEWER_EMAIL"))

    raw_bucket = _env("INBOUND_EMAIL_BUCKET")
    raw_key = f"{_env('INBOUND_EMAIL_PREFIX').rstrip('/')}/{message_id}"
    response = boto3.client("s3", region_name=_env("PUBLISHING_REGION")).get_object(Bucket=raw_bucket, Key=raw_key)
    raw_message = response["Body"].read()
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    body_text = _extract_text(message)
    if not parse_approval_command(body_text):
        return {"status": "ignored", "reason": "first substantive reply line was not approved"}

    registry_s3 = boto3.client("s3", region_name=_env("APPROVAL_REGISTRY_REGION"))
    review = resolve_token_s3(
        s3=registry_s3,
        bucket=_env("APPROVAL_REGISTRY_BUCKET"),
        prefix=_env("APPROVAL_REGISTRY_PREFIX"),
        token=token,
    )
    recipient = str(review.get("recipient") or "")
    if recipient.casefold() != _env("APPROVED_REVIEWER_EMAIL").casefold():
        raise PermissionError("Review package recipient no longer matches the approved reviewer")

    table = boto3.resource("dynamodb", region_name=_env("PUBLISHING_REGION")).Table(_env("PUBLICATIONS_TABLE"))
    ensure_review_control(table=table, review=review)
    review = acquire_review(
        table=table,
        review_id_value=str(review["review_id"]),
        approved_by=f"email:{_env('APPROVED_REVIEWER_EMAIL')}",
    )
    if str(review.get("status")) == "scheduled" and review.get("scheduled_publications"):
        rows = list(review["scheduled_publications"])
        _send_confirmation(review=review, rows=rows)
        return {"status": "already_scheduled", "review_id": review["review_id"], "schedule": rows}

    with tempfile.TemporaryDirectory(prefix="instagram-approval-") as tmp:
        rows = _schedule_review(
            review,
            approved_by=f"email:{_env('APPROVED_REVIEWER_EMAIL')}",
            work_root=Path(tmp),
        )
    mark_scheduled(table=table, review_id_value=str(review["review_id"]), schedule_rows=rows)
    _send_confirmation(review=review, rows=rows)
    return {"status": "scheduled", "review_id": review["review_id"], "schedule": rows}
