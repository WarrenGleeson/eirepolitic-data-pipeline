from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from instagram.factory.render_primitives import ACCENT, TEXT, W, font
from instagram.projects.party_issue_monthly_profile_v2 import adapter as base

_ORIGINAL_RENDER_COVER = base._render_cover

TOP_ISSUE_LABEL = "MOST DISCUSSED ISSUE"
TOP_ISSUE_LABEL_Y = 215
TOP_ISSUE_VALUE_Y = 264
TOP_ISSUE_LABEL_FONT_SIZE = 25
TOP_ISSUE_VALUE_FONT_SIZE = 38


def _top_issue(party: dict[str, Any]) -> tuple[str, int]:
    rows = list(party.get("raw_counts") or [])
    if not rows:
        return "No classified issues", 0
    first = rows[0]
    return str(first.get("label") or first.get("canonical_label") or "Unknown"), int(first.get("value") or 0)


def _render_cover(path: Path, *, party: dict[str, Any], period, project: dict[str, Any], s3) -> dict[str, Any]:
    lineage = _ORIGINAL_RENDER_COVER(path, party=party, period=period, project=project, s3=s3)
    issue, count = _top_issue(party)

    with Image.open(path) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text(
        (W // 2, TOP_ISSUE_LABEL_Y),
        TOP_ISSUE_LABEL,
        font=font(TOP_ISSUE_LABEL_FONT_SIZE, True),
        fill=ACCENT,
        anchor="mm",
    )
    draw.text(
        (W // 2, TOP_ISSUE_VALUE_Y),
        issue,
        font=font(TOP_ISSUE_VALUE_FONT_SIZE, True),
        fill=TEXT,
        anchor="mm",
    )
    image.save(path)

    return {
        **lineage,
        "top_issue_callout": {
            "label": TOP_ISSUE_LABEL,
            "issue": issue,
            "speech_count": count,
            "label_y": TOP_ISSUE_LABEL_Y,
            "issue_y": TOP_ISSUE_VALUE_Y,
            "label_color": ACCENT,
            "issue_color": TEXT,
        },
    }


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    previous = base._render_cover
    base._render_cover = _render_cover
    try:
        return base.generate(project=project, period_spec=period_spec, output_root=output_root)
    finally:
        base._render_cover = previous
