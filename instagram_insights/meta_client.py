from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class MetaResponse:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class MetaInsightsClient:
    """Minimal read-only client for Instagram Graph API Insights calls."""

    def __init__(
        self,
        access_token: str,
        *,
        api_version: str = "v25.0",
        host: str = "graph.facebook.com",
        timeout_seconds: int = 30,
    ) -> None:
        self.access_token = access_token
        self.api_version = api_version
        self.host = host
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> MetaResponse:
        query = dict(params or {})
        query["access_token"] = self.access_token
        encoded = urllib.parse.urlencode(query, doseq=True)
        url = f"https://{self.host}/{self.api_version}/{path.lstrip('/')}?{encoded}"

        request = urllib.request.Request(url=url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return MetaResponse(ok=True, data=payload)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {"error": {"message": str(exc), "code": exc.code}}
            return MetaResponse(ok=False, error=payload.get("error") or payload)
        except Exception as exc:
            return MetaResponse(ok=False, error={"message": str(exc)})

    def account_insight(self, instagram_account_id: str, metric: str, period: str = "day") -> MetaResponse:
        return self.get_json(
            f"{instagram_account_id}/insights",
            {"metric": metric, "period": period},
        )

    def media_insight(self, media_id: str, metric: str) -> MetaResponse:
        return self.get_json(f"{media_id}/insights", {"metric": metric})

    def media_details(self, media_id: str) -> MetaResponse:
        return self.get_json(
            media_id,
            {"fields": "id,media_type,media_product_type,timestamp,permalink"},
        )


def first_metric_value(payload: Dict[str, Any]) -> Any:
    """Extract the first Insights metric value without assuming a fixed Meta response shape."""
    rows: Iterable[Dict[str, Any]] = payload.get("data") or []
    for row in rows:
        values = row.get("values") or []
        if values:
            return values[-1].get("value")
        if "total_value" in row:
            total = row.get("total_value") or {}
            if isinstance(total, dict):
                return total.get("value")
            return total
    return None
