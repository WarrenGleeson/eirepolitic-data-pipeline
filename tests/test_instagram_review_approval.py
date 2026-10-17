from datetime import datetime, timezone
from io import BytesIO

import pytest

from publishing.review_approval import (
    ReviewApprovalConflict,
    next_free_daily_slots,
    parse_approval_command,
    register_review_s3,
    resolve_token_s3,
    review_id,
    standard_party_caption,
)
from publishing.review_approval_lambda import _approval_token, _validate_ses_receipt


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **kwargs):
        self.objects[(Bucket, Key)] = bytes(Body)
        return {}

    def get_object(self, *, Bucket: str, Key: str):
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}


def test_approval_command_is_case_insensitive_and_first_substantive_line_only() -> None:
    assert parse_approval_command("approved\n") is True
    assert parse_approval_command("  APPROVED  \n\nOn Fri someone wrote:\nold text") is True
    assert parse_approval_command("Looks good\napproved") is False
    assert parse_approval_command("") is False


def test_review_id_changes_with_immutable_review_uri() -> None:
    first = review_id(
        project_id="party_issue_monthly_profile_v2",
        period="2026-10",
        source_batch_id="batch-1",
        review_uri="s3://bucket/review/run=1",
        zip_name="party.zip",
    )
    second = review_id(
        project_id="party_issue_monthly_profile_v2",
        period="2026-10",
        source_batch_id="batch-1",
        review_uri="s3://bucket/review/run=2",
        zip_name="party.zip",
    )
    assert first != second
    assert len(first) == 24


def test_s3_registry_resolves_latest_review_and_rejects_superseded_token() -> None:
    s3 = FakeS3()
    first = register_review_s3(
        s3=s3,
        bucket="review-bucket",
        prefix="processed/instagram/review_approvals",
        project_id="party_issue_monthly_profile_v2",
        period="2026-10",
        source_batch_id="batch-1",
        review_uri="s3://review-bucket/processed/instagram/project/run=1",
        zip_name="party.zip",
        recipient="reviewer@example.com",
        sender="sender@example.com",
        now=datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc),
    )
    resolved = resolve_token_s3(
        s3=s3,
        bucket="review-bucket",
        prefix="processed/instagram/review_approvals",
        token=first.token,
        now=datetime(2026, 11, 1, 10, 1, tzinfo=timezone.utc),
    )
    assert resolved["review_id"] == first.review_id

    register_review_s3(
        s3=s3,
        bucket="review-bucket",
        prefix="processed/instagram/review_approvals",
        project_id="party_issue_monthly_profile_v2",
        period="2026-10",
        source_batch_id="batch-1",
        review_uri="s3://review-bucket/processed/instagram/project/run=2",
        zip_name="party.zip",
        recipient="reviewer@example.com",
        sender="sender@example.com",
        now=datetime(2026, 11, 1, 10, 2, tzinfo=timezone.utc),
    )
    with pytest.raises(ReviewApprovalConflict, match="superseded"):
        resolve_token_s3(
            s3=s3,
            bucket="review-bucket",
            prefix="processed/instagram/review_approvals",
            token=first.token,
            now=datetime(2026, 11, 1, 10, 3, tzinfo=timezone.utc),
        )


def test_next_free_8am_utc_slots_skip_occupied_dates() -> None:
    slots = next_free_daily_slots(
        scheduled_at_utc_values=[
            "2026-11-02T08:00:00Z",
            "2026-11-04T08:00:00Z",
            "2026-11-03T12:00:00Z",
        ],
        count=3,
        hour_utc=8,
        now=datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert [value.isoformat() for value in slots] == [
        "2026-11-03T08:00:00+00:00",
        "2026-11-05T08:00:00+00:00",
        "2026-11-06T08:00:00+00:00",
    ]


def test_next_free_slot_can_use_same_day_when_safely_in_future() -> None:
    slots = next_free_daily_slots(
        scheduled_at_utc_values=[],
        count=1,
        hour_utc=8,
        now=datetime(2026, 11, 1, 6, 0, tzinfo=timezone.utc),
    )
    assert slots[0].isoformat() == "2026-11-01T08:00:00+00:00"


def test_standard_party_caption_uses_month_party_and_approved_tags() -> None:
    caption = standard_party_caption(party="Sinn Féin", period="2026-10")
    assert "Sinn Féin" in caption
    assert "October 2026" in caption
    assert "not the party’s position" in caption
    assert caption.endswith("#EirePolitic #Oireachtas #IrishPolitics #DáilÉireann #PoliticalData")


def test_token_is_extracted_from_plus_address() -> None:
    assert _approval_token(["approve+abc_DEF-123@instagram.example.com"]) == "abc_DEF-123"


def test_ses_receipt_requires_authorized_sender_and_clean_verdicts() -> None:
    record = {
        "ses": {
            "mail": {
                "messageId": "message-1",
                "source": "Warrengleeson97@gmail.com",
                "destination": ["approve+token123@instagram.example.com"],
            },
            "receipt": {
                "recipients": ["approve+token123@instagram.example.com"],
                "spamVerdict": {"status": "PASS"},
                "virusVerdict": {"status": "PASS"},
            },
        }
    }
    assert _validate_ses_receipt(record, approved_sender="warrengleeson97@gmail.com") == ("message-1", "token123")
    record["ses"]["mail"]["source"] = "other@example.com"
    with pytest.raises(PermissionError):
        _validate_ses_receipt(record, approved_sender="warrengleeson97@gmail.com")
