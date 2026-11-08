from instagram_insights.collector import (
    PublishedMedia,
    collect_account_metrics,
    collect_media_metrics,
    list_published_media,
)
from instagram_insights.meta_client import MetaResponse


class FakeTable:
    def __init__(self, scan_items=None):
        self.scan_items = scan_items or []
        self.writes = []

    def scan(self, **kwargs):
        return {"Items": self.scan_items}

    def put_item(self, Item):
        self.writes.append(Item)
        return {}


class FakeClient:
    def account_insight(self, account_id, metric, period="day"):
        if metric == "reach":
            return MetaResponse(ok=True, data={"data": [{"values": [{"value": 123}]}]})
        return MetaResponse(ok=False, error={"code": 100, "message": "unsupported"})

    def media_details(self, media_id):
        return MetaResponse(
            ok=True,
            data={
                "id": media_id,
                "media_type": "CAROUSEL_ALBUM",
                "media_product_type": "FEED",
                "timestamp": "2026-11-01T12:00:00+0000",
            },
        )

    def media_insight(self, media_id, metric):
        if metric == "reach":
            return MetaResponse(ok=True, data={"data": [{"values": [{"value": 55}]}]})
        return MetaResponse(ok=False, error={"code": 100, "message": "unsupported"})


def test_list_published_media_joins_control_and_execution_by_publication_version():
    table = FakeTable(
        [
            {
                "entity_type": "publication_control",
                "publication_id": "pub-1",
                "publication_version": 2,
                "request": {
                    "publication_id": "pub-1",
                    "publication_version": 2,
                    "project_id": "bill-tracker",
                    "period": "2026-11",
                },
            },
            {
                "entity_type": "execution_attempt",
                "publication_id": "pub-1",
                "publication_version": 2,
                "attempt": {
                    "publication_id": "pub-1",
                    "publication_version": 2,
                    "published_media_id": "ig-123",
                },
            },
            {
                "entity_type": "execution_attempt",
                "publication_id": "pub-1",
                "publication_version": 1,
                "attempt": {
                    "publication_id": "pub-1",
                    "publication_version": 1,
                    "published_media_id": "old-media",
                },
            },
        ]
    )

    result = list_published_media(table)

    assert result == [
        PublishedMedia(
            publication_id="pub-1",
            publication_version=2,
            project_id="bill-tracker",
            period="2026-11",
            media_id="ig-123",
        )
    ]


def test_account_collection_records_success_and_unsupported_metrics():
    table = FakeTable()
    statuses = collect_account_metrics(
        table,
        FakeClient(),
        instagram_account_id="ig-account",
        snapshot_at="2026-11-07T20:00:00Z",
        metrics=("reach", "views"),
    )

    assert statuses == {"reach": "ok", "views": "unsupported_or_error"}
    assert len(table.writes) == 2
    assert table.writes[0]["value"] == 123
    assert table.writes[1]["error"]["code"] == 100


def test_media_collection_preserves_publication_dimensions():
    table = FakeTable()
    media = PublishedMedia(
        publication_id="pub-1",
        publication_version=2,
        project_id="bill-tracker",
        period="2026-11",
        media_id="ig-123",
    )

    statuses = collect_media_metrics(
        table,
        FakeClient(),
        published_media=(media,),
        snapshot_at="2026-11-07T20:00:00Z",
        metrics=("reach", "saved"),
    )

    assert statuses == {"ig-123": {"reach": "ok", "saved": "unsupported_or_error"}}
    assert table.writes[0]["publication_id"] == "pub-1"
    assert table.writes[0]["project_id"] == "bill-tracker"
    assert table.writes[0]["media_type"] == "CAROUSEL_ALBUM"
