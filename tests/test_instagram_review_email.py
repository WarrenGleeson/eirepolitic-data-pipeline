from __future__ import annotations

from instagram.factory.review_email import DEFAULT_S3_REGION, build_message, build_review_links


class FakeS3:
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        assert operation == "get_object"
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?ttl={ExpiresIn}"


def test_review_link_signing_region_matches_review_bucket() -> None:
    assert DEFAULT_S3_REGION == "us-east-2"


def test_review_links_are_private_presigned_review_assets() -> None:
    links = build_review_links(
        s3=FakeS3(),
        review_uri="s3://eirepolitic-data/processed/instagram/project/period=2026-09/source_batch=batch-1/github_run=123",
        zip_path="instagram/production/output/project-september-2026.zip",
        ttl_seconds=604800,
    )
    assert links["overview"].endswith("contact_sheets/five_slide_overview.jpg?ttl=604800")
    assert links["zip"].endswith("project-september-2026.zip?ttl=604800")
    assert links["qa"].endswith("qa_summary.csv?ttl=604800")
    assert links["manifest"].endswith("run_manifest.json?ttl=604800")


def test_review_message_preserves_human_review_and_no_publish_semantics() -> None:
    report = {
        "status": "PASS",
        "party_count": 11,
        "slide_count": 55,
        "qa": {"passed": 55, "failed": 0},
        "review_state": "pending_human_review",
        "publication_enabled": False,
    }
    links = {
        "overview": "https://example.test/overview",
        "zip": "https://example.test/zip",
        "qa": "https://example.test/qa",
        "manifest": "https://example.test/manifest",
    }
    subject, text_body, html_body = build_message(
        project_id="party_issue_monthly_profile_v2",
        period="2026-09",
        source_batch_id="batch-1",
        report=report,
        links=links,
        github_run_url="https://github.com/example/actions/runs/123",
    )
    assert subject == "Review: Party Speech Breakdown — September 2026"
    assert "55 passed / 0 failed" in text_body
    assert "pending_human_review" in text_body
    assert "Publishing enabled: false" in text_body
    assert "No Instagram publication has been scheduled or published" in text_body
    assert "View five-slide overview" in html_body
    assert "publishing</strong></td><td>disabled" in html_body.lower()
