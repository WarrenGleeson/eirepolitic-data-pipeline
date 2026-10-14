from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from instagram.factory.render_primitives import ACCENT, TEXT, W, fit_font, font
from instagram.projects.party_issue_monthly_profile_v2 import adapter as base

_ORIGINAL_RENDER_COVER = base._render_cover

TOP_ISSUE_LABEL_SINGULAR = "MOST DISCUSSED ISSUE"
TOP_ISSUE_LABEL_PLURAL = "MOST DISCUSSED ISSUES"
TOP_ISSUE_LABEL_Y = 215
TOP_ISSUE_VALUE_Y = 264
TOP_ISSUE_LABEL_FONT_SIZE = 25
TOP_ISSUE_VALUE_FONT_SIZE = 38
TOP_ISSUE_VALUE_MIN_FONT_SIZE = 22
TOP_ISSUE_VALUE_MAX_WIDTH = 820
TOP_ISSUE_SEPARATOR = " • "
TOP_ISSUE_METRICS = ("raw_counts", "share_vs_average", "per_td_vs_average")


def _row_label(row: dict[str, Any]) -> str:
    return str(row.get("label") or row.get("canonical_label") or "Unknown")


def _top_issues(party: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for metric in TOP_ISSUE_METRICS:
        rows = list(party.get(metric) or [])
        if not rows:
            continue
        issue = _row_label(rows[0])
        canonical = str(rows[0].get("canonical_label") or issue).strip().casefold()
        if canonical in seen:
            continue
        seen.add(canonical)
        issues.append(issue)
    return issues


def _top_issue_label(issues: list[str]) -> str:
    return TOP_ISSUE_LABEL_SINGULAR if len(issues) == 1 else TOP_ISSUE_LABEL_PLURAL


def _render_cover(path: Path, *, party: dict[str, Any], period, project: dict[str, Any], s3) -> dict[str, Any]:
    lineage = _ORIGINAL_RENDER_COVER(path, party=party, period=period, project=project, s3=s3)
    issues = _top_issues(party)
    if not issues:
        issues = ["No classified issues"]
    label = _top_issue_label(issues)
    issue_text = TOP_ISSUE_SEPARATOR.join(issues)

    with Image.open(path) as opened:
        image = opened.convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text(
        (W // 2, TOP_ISSUE_LABEL_Y),
        label,
        font=font(TOP_ISSUE_LABEL_FONT_SIZE, True),
        fill=ACCENT,
        anchor="mm",
    )
    value_font = fit_font(
        draw,
        issue_text,
        TOP_ISSUE_VALUE_MAX_WIDTH,
        TOP_ISSUE_VALUE_FONT_SIZE,
        TOP_ISSUE_VALUE_MIN_FONT_SIZE,
        bold=True,
    )
    draw.text(
        (W // 2, TOP_ISSUE_VALUE_Y),
        issue_text,
        font=value_font,
        fill=TEXT,
        anchor="mm",
    )
    value_bbox = draw.textbbox((W // 2, TOP_ISSUE_VALUE_Y), issue_text, font=value_font, anchor="mm")
    if value_bbox[0] < (W - TOP_ISSUE_VALUE_MAX_WIDTH) // 2 or value_bbox[2] > (W + TOP_ISSUE_VALUE_MAX_WIDTH) // 2:
        raise RuntimeError(f"Top issue callout exceeds approved width: {issue_text!r} -> {value_bbox}")
    image.save(path)

    return {
        **lineage,
        "top_issue_callout": {
            "label": label,
            "issues": issues,
            "issue_text": issue_text,
            "issue_count": len(issues),
            "source_metrics": list(TOP_ISSUE_METRICS),
            "label_y": TOP_ISSUE_LABEL_Y,
            "issue_y": TOP_ISSUE_VALUE_Y,
            "label_color": ACCENT,
            "issue_color": TEXT,
            "issue_max_width_px": TOP_ISSUE_VALUE_MAX_WIDTH,
            "issue_bbox_px": [int(value) for value in value_bbox],
        },
    }


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    previous = base._render_cover
    base._render_cover = _render_cover
    try:
        return base.generate(project=project, period_spec=period_spec, output_root=output_root)
    finally:
        base._render_cover = previous
