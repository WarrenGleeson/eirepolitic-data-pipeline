from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from urllib.parse import urlparse

import boto3

from publishing.review_approval import register_review

DEFAULT_SES_REGION = "us-east-2"
DEFAULT_S3_REGION = "us-east-2"
DEFAULT_URL_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_APPROVAL_TABLE = "eirepolitic-publications"
DEFAULT_APPROVAL_REGION = "us-east-2"


def _s3_parts(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Expected s3:// URI, got {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/").rstrip("/")


def _presign(s3, *, bucket: str, key: str, ttl_seconds: int) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=ttl_seconds,
    )


def build_review_links(
    *,
    s3,
    review_uri: str,
    zip_path: str,
    ttl_seconds: int = DEFAULT_URL_TTL_SECONDS,
) -> dict[str, str]:
    bucket, prefix = _s3_parts(review_uri)
    zip_name = Path(zip_path).name
    keys = {
        "overview": f"{prefix}/contact_sheets/five_slide_overview.jpg",
        "zip": f"{prefix}/{zip_name}",
        "qa": f"{prefix}/qa_summary.csv",
        "manifest": f"{prefix}/run_manifest.json",
    }
    return {
        name: _presign(s3, bucket=bucket, key=key, ttl_seconds=ttl_seconds)
        for name, key in keys.items()
    }


def _display_period(period: str) -> str:
    try:
        year, month = period.split("-", 1)
        import datetime as dt

        return dt.date(int(year), int(month), 1).strftime("%B %Y")
    except Exception:
        return period


def build_message(
    *,
    project_id: str,
    period: str,
    source_batch_id: str,
    report: dict,
    links: dict[str, str],
    github_run_url: str,
    ttl_days: int = 7,
    approval_enabled: bool = False,
) -> tuple[str, str, str]:
    display_period = _display_period(period)
    subject = f"Review: Party Speech Breakdown — {display_period}"
    qa = report.get("qa") or {}
    party_count = report.get("party_count", "unknown")
    slide_count = report.get("slide_count", "unknown")
    passed = qa.get("passed", "unknown")
    failed = qa.get("failed", "unknown")
    approval_text = (
        "\nTo approve and schedule this exact reviewed package, reply with only: approved\n"
        if approval_enabled
        else ""
    )
    approval_html = (
        "<p><strong>To approve and schedule this exact reviewed package, reply with only: <code>approved</code></strong></p>"
        if approval_enabled
        else ""
    )

    text_body = f"""EirePolitic Party Speech Breakdown review is ready.

Period: {display_period}
Project: {project_id}
Source batch: {source_batch_id}
Parties/groups: {party_count}
Slides: {slide_count}
QA: {passed} passed / {failed} failed
Review state: pending_human_review
Publishing enabled: false

Five-slide overview: {links['overview']}
Download ZIP: {links['zip']}
QA CSV: {links['qa']}
Run manifest: {links['manifest']}
GitHub run: {github_run_url}
{approval_text}
Private review links expire in {ttl_days} days.
No Instagram publication has been scheduled or published by this email.
"""

    html_body = f"""
    <html><body style="font-family:Arial,sans-serif;line-height:1.5;color:#1f2937">
      <h2>EirePolitic Party Speech Breakdown</h2>
      <p>The <strong>{html.escape(display_period)}</strong> review package is ready.</p>
      <table style="border-collapse:collapse">
        <tr><td style="padding:4px 12px 4px 0"><strong>Source batch</strong></td><td>{html.escape(source_batch_id)}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Parties/groups</strong></td><td>{html.escape(str(party_count))}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Slides</strong></td><td>{html.escape(str(slide_count))}</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>QA</strong></td><td>{html.escape(str(passed))} passed / {html.escape(str(failed))} failed</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Review state</strong></td><td>pending_human_review</td></tr>
        <tr><td style="padding:4px 12px 4px 0"><strong>Publishing</strong></td><td>disabled</td></tr>
      </table>
      <p style="margin-top:20px">
        <a href="{html.escape(links['overview'])}">View five-slide overview</a><br>
        <a href="{html.escape(links['zip'])}">Download full ZIP</a><br>
        <a href="{html.escape(links['qa'])}">Open QA summary</a><br>
        <a href="{html.escape(links['manifest'])}">Open run manifest</a><br>
        <a href="{html.escape(github_run_url)}">Open GitHub Actions run</a>
      </p>
      {approval_html}
      <p><small>The private review links expire in {ttl_days} days. No Instagram publication has been scheduled or published by this email.</small></p>
    </body></html>
    """
    return subject, text_body, html_body


def send_review_email(
    *,
    report_path: Path,
    review_uri: str,
    zip_path: str,
    source_batch_id: str,
    period: str,
    project_id: str,
    recipient: str,
    sender: str,
    github_run_url: str,
    ses_region: str = DEFAULT_SES_REGION,
    s3_region: str = DEFAULT_S3_REGION,
    ttl_seconds: int = DEFAULT_URL_TTL_SECONDS,
    approval_domain: str | None = None,
    approval_table: str = DEFAULT_APPROVAL_TABLE,
    approval_region: str = DEFAULT_APPROVAL_REGION,
) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS":
        raise RuntimeError(f"Refusing review email for non-PASS generation: {report.get('status')}")
    if report.get("publication_enabled") is not False:
        raise RuntimeError("Refusing review email because publication_enabled is not false")
    if report.get("review_state") != "pending_human_review":
        raise RuntimeError(f"Unexpected review state: {report.get('review_state')}")

    approval_record = None
    reply_to = None
    if approval_domain:
        table = boto3.resource("dynamodb", region_name=approval_region).Table(approval_table)
        approval_record = register_review(
            table=table,
            project_id=project_id,
            period=period,
            source_batch_id=source_batch_id,
            review_uri=review_uri,
            zip_name=Path(zip_path).name,
            recipient=recipient,
            sender=sender,
        )
        reply_to = f"approve+{approval_record.token}@{approval_domain.strip().lower()}"

    s3 = boto3.client("s3", region_name=s3_region)
    links = build_review_links(
        s3=s3,
        review_uri=review_uri,
        zip_path=zip_path,
        ttl_seconds=ttl_seconds,
    )
    subject, text_body, html_body = build_message(
        project_id=project_id,
        period=period,
        source_batch_id=source_batch_id,
        report=report,
        links=links,
        github_run_url=github_run_url,
        ttl_days=max(1, ttl_seconds // 86400),
        approval_enabled=bool(reply_to),
    )

    ses = boto3.client("sesv2", region_name=ses_region)
    request = {
        "FromEmailAddress": sender,
        "Destination": {"ToAddresses": [recipient]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": text_body, "Charset": "UTF-8"},
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                },
            }
        },
    }
    if reply_to:
        request["ReplyToAddresses"] = [reply_to]
    response = ses.send_email(**request)
    return {
        "status": "sent",
        "message_id": response.get("MessageId"),
        "recipient": recipient,
        "sender": sender,
        "reply_to": reply_to,
        "approval_enabled": bool(reply_to),
        "approval_review_id": approval_record.review_id if approval_record else None,
        "ses_region": ses_region,
        "s3_region": s3_region,
        "period": period,
        "project_id": project_id,
        "source_batch_id": source_batch_id,
        "review_state": report.get("review_state"),
        "publication_enabled": report.get("publication_enabled"),
        "link_expiry_seconds": ttl_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send an SES review email for a completed Instagram factory run")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--review-uri", required=True)
    parser.add_argument("--zip-path", required=True)
    parser.add_argument("--source-batch-id", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--sender", required=True)
    parser.add_argument("--github-run-url", required=True)
    parser.add_argument("--ses-region", default=DEFAULT_SES_REGION)
    parser.add_argument("--s3-region", default=DEFAULT_S3_REGION)
    parser.add_argument("--approval-domain", default="")
    parser.add_argument("--approval-table", default=DEFAULT_APPROVAL_TABLE)
    parser.add_argument("--approval-region", default=DEFAULT_APPROVAL_REGION)
    args = parser.parse_args()

    result = send_review_email(
        report_path=args.report,
        review_uri=args.review_uri,
        zip_path=args.zip_path,
        source_batch_id=args.source_batch_id,
        period=args.period,
        project_id=args.project_id,
        recipient=args.recipient,
        sender=args.sender,
        github_run_url=args.github_run_url,
        ses_region=args.ses_region,
        s3_region=args.s3_region,
        approval_domain=(args.approval_domain or None),
        approval_table=args.approval_table,
        approval_region=args.approval_region,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
