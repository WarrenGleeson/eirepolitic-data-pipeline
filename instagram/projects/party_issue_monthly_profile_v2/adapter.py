from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import yaml
from PIL import Image, ImageDraw

from instagram.factory.oireachtas_source import (
    load_csv_tables,
    require_completed_calendar_month,
    resolve_validated_production_batch,
)
from instagram.factory.package import deterministic_zip
from instagram.factory.party_asset_registry import fetch_logo, resolve_party_asset
from instagram.factory.render_primitives import (
    ACCENT,
    BG,
    H,
    MUTED,
    TEXT,
    W,
    base_slide,
    carousel_sheet,
    contact_sheet,
    draw_glossary,
    draw_title,
    fit_font,
    font,
    period_dates,
    prepare_square_logo,
)
from instagram.renderer.template_renderer import render_template
from instagram.visuals.renderers import horizontal_bar
from political_metrics.calculators.issues import attach_issue_labels, policy_speeches
from political_metrics.commission import prepare_eligible_td_speeches
from political_metrics.issue_audit import audit_issue_classification
from political_metrics.periods import resolve_period
from political_metrics.sources import canonical_speeches
from political_metrics.temporal_joins import attach_event_membership, attach_event_party

PROJECT_ID = "party_issue_monthly_profile_v2"
LABELS_PATH = Path("instagram/reference/issue_presentation_labels.yml")
ASSET_REGISTRY_PATH = "configs/reference/party_assets_v1.csv"
APPROVED_VARIANT_SOURCE = {
    "variant": 2,
    "source_family": "Matplotlib final January commissioning",
    "source_commit": "7f10fb0454d0da6d58b4c5c5b2e5aacc39844052",
    "source_run_number": 203,
    "source_run_id": 33448590338,
    "commissioning_reference_branch": "commissioning/instagram-party-monthly-profile-v2",
    "commissioning_reference_run_number": 247,
    "commissioning_reference_run_id": 33800066946,
}

GLOSSARY = [
    (
        "Most Discussed Issues",
        "The issues this party/group talked about most often during the month, based on the number of classified speeches.",
    ),
    (
        "Issues Discussed More Than Average",
        "Issues that made up a larger share of this party/group's classified speeches than the simple average across parties. Values show percentage points above average.",
    ),
    (
        "Issues Discussed More Than Average per TD",
        "Issues where this party/group recorded more classified speeches per TD than the simple average across parties. This adjusts the comparison for party size.",
    ),
    (
        "Classified Speeches",
        "Speech segments assigned to an issue category. Counts show how often an issue was discussed, not the party/group's position on it.",
    ),
]


def _display_party_name(name: str) -> str:
    return "Independents" if name == "Independent" else name


def _period_label(period) -> str:
    return period.start.strftime("%B %Y")


def _load_presentation_labels() -> dict[str, str]:
    payload = yaml.safe_load(LABELS_PATH.read_text(encoding="utf-8")) or {}
    return {str(key): str(value) for key, value in (payload.get("labels") or {}).items()}


def _period_end_party_snapshot(
    memberships: pd.DataFrame,
    parties: pd.DataFrame,
    *,
    period,
) -> pd.DataFrame:
    member_codes = sorted(set(memberships["member_code"].dropna().astype(str)))
    events = pd.DataFrame({"member_code": member_codes, "event_date": period.end.isoformat()})
    joined = attach_event_membership(events, memberships, event_date_col="event_date")
    joined = joined[joined["membership_id"].notna()].copy()
    if "chamber" in joined.columns:
        joined = joined[joined["chamber"].fillna("").astype(str).str.lower().eq("dail")].copy()
    joined = attach_event_party(joined, parties, event_date_col="event_date")
    joined = joined[joined["party_name"].notna() & joined["party_uri"].notna()].copy()
    if joined["member_code"].duplicated().any():
        duplicates = joined.loc[joined["member_code"].duplicated(keep=False), "member_code"].astype(str).unique().tolist()
        raise RuntimeError(f"Period-end Dáil snapshot has duplicate member rows: {duplicates[:10]}")
    if joined.empty:
        raise RuntimeError(f"No active Dáil party snapshot could be resolved for {period.end}")
    return joined[["member_code", "party_uri", "party_name"]].reset_index(drop=True)


def _prepare_metrics(frames: dict[str, pd.DataFrame], *, period, expected_party_count: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    speeches = canonical_speeches(frames["silver_speeches"])
    labels = frames["enrichment_speech_issue_labels"]
    memberships = frames["silver_member_memberships"]
    parties = frames["silver_member_parties"]
    constituencies = frames["silver_member_constituencies"]

    classification_gate = audit_issue_classification(
        speeches,
        labels,
        period_start=period.start.isoformat(),
        period_end=period.end.isoformat(),
    )
    if not classification_gate.get("ready"):
        raise RuntimeError(f"Issue classification readiness failed for {period.start:%Y-%m}: {classification_gate}")

    eligible = prepare_eligible_td_speeches(
        speeches,
        memberships,
        parties,
        constituencies,
        period,
    )
    if eligible.empty:
        raise RuntimeError(f"No Dáil-eligible speeches found for {period.start:%Y-%m}")
    missing_party = eligible[eligible["party_uri"].isna() | eligible["party_name"].isna()]
    if not missing_party.empty:
        examples = missing_party[[col for col in ["speech_id", "member_code", "debate_date"] if col in missing_party.columns]].head(10)
        raise RuntimeError(
            f"Period-correct party attribution failed for {len(missing_party)} Dáil-eligible speeches: "
            f"{examples.to_dict(orient='records')}"
        )

    eligible_with_labels = attach_issue_labels(eligible, labels)
    policy = policy_speeches(eligible_with_labels)
    if policy.empty:
        raise RuntimeError(f"No classified policy speeches found for {period.start:%Y-%m}")
    if policy["speech_id"].duplicated().any():
        raise RuntimeError("Party metric input contains duplicate speech_id values")

    snapshot = _period_end_party_snapshot(memberships, parties, period=period)
    snapshot_counts = (
        snapshot.groupby(["party_uri", "party_name"], dropna=False)["member_code"]
        .nunique()
        .rename("td_count")
        .reset_index()
    )
    if len(snapshot_counts) != expected_party_count:
        found = sorted(snapshot_counts["party_name"].astype(str).tolist())
        raise RuntimeError(
            f"Expected {expected_party_count} active Dáil parties/groups at period end; "
            f"found {len(snapshot_counts)}: {found}"
        )

    display_parties: list[dict[str, Any]] = []
    seen_asset_keys: set[str] = set()
    for row in snapshot_counts.itertuples(index=False):
        party_name = str(row.party_name)
        asset = resolve_party_asset(party_name)
        if asset.party_key in seen_asset_keys:
            raise RuntimeError(f"Duplicate canonical party asset key in period snapshot: {asset.party_key}")
        seen_asset_keys.add(asset.party_key)
        display_parties.append(
            {
                "party_uri": str(row.party_uri),
                "party": party_name,
                "display_party_name": _display_party_name(party_name),
                "party_key": asset.party_key,
                "td_count": int(row.td_count),
            }
        )
    display_parties.sort(key=lambda item: item["party"])

    active_names = {item["party"] for item in display_parties}
    speech_names = set(policy["party_name"].dropna().astype(str))
    unknown_speech_parties = sorted(speech_names - active_names)
    if unknown_speech_parties:
        raise RuntimeError(
            "One or more period-attributed speech parties are not represented in the period-end display universe: "
            f"{unknown_speech_parties}"
        )

    labels_for_chart = _load_presentation_labels()
    categories = sorted(policy["issue_label"].dropna().astype(str).unique().tolist())
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    party_totals: dict[str, int] = {}
    for item in display_parties:
        party_name = item["party"]
        scoped = policy[policy["party_name"].astype(str).eq(party_name)]
        party_totals[party_name] = int(scoped["speech_id"].nunique())
        grouped = scoped.groupby("issue_label")["speech_id"].nunique().to_dict()
        counts[party_name] = {str(category): int(value) for category, value in grouped.items()}

    share_baseline: dict[str, float] = {}
    per_td_baseline: dict[str, float] = {}
    for category in categories:
        shares: list[float] = []
        per_td_rates: list[float] = []
        for item in display_parties:
            party_name = item["party"]
            count = counts[party_name].get(category, 0)
            total = party_totals[party_name]
            shares.append(count / total if total else 0.0)
            per_td_rates.append(count / item["td_count"] if item["td_count"] else 0.0)
        share_baseline[category] = sum(shares) / len(display_parties)
        per_td_baseline[category] = sum(per_td_rates) / len(display_parties)

    max_items = 7
    result: list[dict[str, Any]] = []
    for item in display_parties:
        party_name = item["party"]
        total = party_totals[party_name]
        td_count = int(item["td_count"])
        raw_rows = sorted(
            [
                {
                    "canonical_label": category,
                    "label": labels_for_chart.get(category, category),
                    "value": counts[party_name].get(category, 0),
                }
                for category in categories
                if counts[party_name].get(category, 0) > 0
            ],
            key=lambda row: (-int(row["value"]), str(row["canonical_label"])),
        )[:max_items]
        share_rows: list[dict[str, Any]] = []
        per_td_rows: list[dict[str, Any]] = []
        for category in categories:
            count = counts[party_name].get(category, 0)
            actual_share = count / total if total else 0.0
            share_delta = (actual_share - share_baseline[category]) * 100.0
            if share_delta > 0:
                share_rows.append(
                    {
                        "canonical_label": category,
                        "label": labels_for_chart.get(category, category),
                        "value": share_delta,
                        "raw_count": count,
                    }
                )
            actual_rate = count / td_count if td_count else 0.0
            rate_delta = actual_rate - per_td_baseline[category]
            if rate_delta > 0:
                per_td_rows.append(
                    {
                        "canonical_label": category,
                        "label": labels_for_chart.get(category, category),
                        "value": rate_delta,
                        "raw_count": count,
                    }
                )
        share_rows.sort(key=lambda row: (-float(row["value"]), str(row["canonical_label"])))
        per_td_rows.sort(key=lambda row: (-float(row["value"]), str(row["canonical_label"])))
        share_rows = share_rows[:max_items]
        per_td_rows = per_td_rows[:max_items]
        result.append(
            {
                **item,
                "classified_speeches": total,
                "avg_speeches_per_td": total / td_count if td_count else 0.0,
                "raw_counts": raw_rows,
                "share_vs_average": share_rows,
                "per_td_vs_average": per_td_rows,
            }
        )

    readiness = {
        "classification_gate": classification_gate,
        "period_eligible_dail_speeches": int(eligible["speech_id"].nunique()),
        "period_policy_speeches": int(policy["speech_id"].nunique()),
        "matched_classified_rows": int(policy["speech_id"].nunique()),
        "unmatched_classified_rows": int(len(missing_party)),
        "party_count": len(result),
        "period_end_active_td_count": int(snapshot["member_code"].nunique()),
        "issue_count": len(categories),
    }
    return result, readiness


def _render_cover(path: Path, *, party: dict[str, Any], period, project: dict[str, Any], s3) -> dict[str, Any]:
    cover_cfg = (project.get("render") or {}).get("cover") or {}
    title = str(cover_cfg.get("title") or "Party Speech Breakdown")
    period_label = _period_label(period)
    logo_size = int(cover_cfg.get("logo_size", 500))
    logo_top = int(cover_cfg.get("logo_top", 300))
    border_width = int(cover_cfg.get("logo_border_width", 6))
    border_color = str(cover_cfg.get("logo_border_color") or ACCENT)
    scale_overrides = {str(key): float(value) for key, value in (cover_cfg.get("scale_overrides") or {}).items()}
    cleanup_keys = {str(value) for value in (cover_cfg.get("neutral_cleanup_party_keys") or [])}

    image = base_slide()
    draw_title(image, [title, period_label])
    draw = ImageDraw.Draw(image)
    asset = resolve_party_asset(party["party"])
    if asset.party_key != party["party_key"]:
        raise RuntimeError(f"Party registry key mismatch for {party['party']}: {asset.party_key} vs {party['party_key']}")
    logo, asset_lineage = fetch_logo(s3, asset)
    logo, prep = prepare_square_logo(
        logo,
        party_key=party["party_key"],
        size=logo_size,
        scale_overrides=scale_overrides,
        neutral_cleanup_keys=cleanup_keys,
    )
    logo_left = (W - logo_size) // 2
    logo_right = logo_left + logo_size - 1
    logo_bottom = logo_top + logo_size - 1
    image.paste(logo, (logo_left, logo_top))
    draw.rectangle((logo_left, logo_top, logo_right, logo_bottom), outline=border_color, width=border_width)

    raw_counts = party.get("raw_counts") or []
    featured_issue = str(raw_counts[0]["label"]) if raw_counts else "No dominant issue identified"
    featured_label_font = font(24, True)
    featured_issue_font = fit_font(draw, featured_issue, 820, 48, 30, bold=True)
    draw.text((540, 842), "MOST DISCUSSED ISSUE", font=featured_label_font, fill=ACCENT, anchor="mm")
    draw.text((540, 895), featured_issue, font=featured_issue_font, fill=TEXT, anchor="mm")

    number_font = font(72, True)
    label_font = font(25, True)
    small_font = font(24)
    draw.text((294, 980), f"{party['classified_speeches']:,}", font=number_font, fill=TEXT, anchor="mm")
    draw.text((294, 1047), "CLASSIFIED SPEECHES", font=label_font, fill=ACCENT, anchor="mm")
    draw.text((786, 980), f"{party['avg_speeches_per_td']:.1f}", font=number_font, fill=TEXT, anchor="mm")
    draw.text((786, 1047), "AVG SPEECHES PER TD", font=label_font, fill=ACCENT, anchor="mm")
    draw.line((239, 1115, 841, 1115), fill=ACCENT, width=3)
    draw.text((540, 1170), period_label.upper(), font=label_font, fill=ACCENT, anchor="mm")
    draw.text((540, 1218), period_dates(period), font=small_font, fill=TEXT, anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)

    return {
        "party_asset": asset_lineage,
        "cover_title": title,
        "cover_title_period": period_label,
        "featured_issue_label": "Most Discussed Issue",
        "featured_issue": featured_issue,
        "display_party_name": party["display_party_name"],
        "logo_geometry": {
            "square_size": [logo_size, logo_size],
            "top": logo_top,
            "left": logo_left,
            "centered": True,
            "artwork_scale": prep["artwork_scale"],
            "border": {"enabled": True, "color": border_color, "width_px": border_width, "position": "inside_square"},
        },
        "logo_resampling_cleanup": {
            "enabled": party["party_key"] in cleanup_keys,
            "neutral_pixels_replaced": prep["neutral_pixels_replaced"],
            "purpose": "remove_neutral_gray_pixels_introduced_by_lanczos_downscaling",
        },
    }


def _variant_template(project: dict[str, Any], value_format: str) -> dict[str, Any]:
    render_cfg = project.get("render") or {}
    palette = render_cfg.get("palette") or {}
    return {
        "template_id": "horizontal_bar_draft_v1",
        "params": {
            "width": 1032,
            "height": 1210,
            "max_items": 7,
            "sort": "descending",
            "value_format": value_format,
            "min_visual_rows": int(render_cfg.get("min_visual_rows", 4)),
        },
        "palette": {
            "background": str(palette.get("background") or BG),
            "panel": str(palette.get("background") or BG),
            "text": str(palette.get("text") or TEXT),
            "muted": str(palette.get("muted") or MUTED),
            "accent": str(palette.get("accent") or ACCENT),
            "grid": str(palette.get("grid") or TEXT),
        },
    }


def _render_analytical(
    path: Path,
    *,
    party: dict[str, Any],
    period,
    project: dict[str, Any],
    rows: list[dict[str, Any]],
    slide_id: str,
    slide_title: str,
    metric_id: str,
    value_format: str,
    source_batch_id: str,
) -> dict[str, Any]:
    party_root = path.parent.parent
    assets_dir = party_root / "assets" / "variant-2"
    metadata_dir = party_root / "metadata" / "variant-2"
    visual_path = assets_dir / f"{path.stem}-visual.png"
    metadata_path = metadata_dir / f"{path.stem}-visual.json"
    visual_manifest_path = metadata_dir / f"{path.stem}-visual-manifest.json"
    assets_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    sample = {
        "visual_id": f"{party['party_key']}-{metric_id}-variant-2",
        "bindings": {"label": "label", "value": "value"},
        "source_note": f"{_period_label(period)} Dáil speeches · Houses of the Oireachtas / Eirepolitic classification",
        "empty_message": {
            "raw_counts": "No classified issues this month",
            "share_vs_average": "No issues above average",
            "per_td_vs_average": "No issues above average per TD",
        }.get(metric_id, "No data available"),
    }
    visual_manifest = horizontal_bar.render(
        _variant_template(project, value_format),
        sample,
        rows,
        visual_path,
        metadata_path,
        visual_manifest_path,
        {
            "project_id": PROJECT_ID,
            "source_batch_id": source_batch_id,
            "period_start": period.start.isoformat(),
            "period_end": period.end.isoformat(),
            "party": party["party"],
            "party_key": party["party_key"],
            "metric_id": metric_id,
            "presentation_labels_path": str(LABELS_PATH),
            "approved_visual_variant": 2,
            "approved_visual_source_run_id": APPROVED_VARIANT_SOURCE["source_run_id"],
        },
    )
    if visual_manifest.get("warnings"):
        raise RuntimeError(f"Visual QA warnings for {party['party']}/{slide_id}: {visual_manifest['warnings']}")

    layout_path = Path(str((project.get("render") or {})["outer_layout"]))
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    rendered = render_template(layout, {"slide_title": slide_title, "body_text": "", "main_media": str(visual_path), "footer_text": ""}, path)
    if rendered.warnings:
        raise RuntimeError(f"Outer layout warnings for {party['party']}/{slide_id}: {rendered.warnings}")

    return {
        **APPROVED_VARIANT_SOURCE,
        "renderer": "instagram.visuals.renderers.horizontal_bar",
        "outer_layout": str(layout_path),
        "slide_id": slide_id,
        "slide_title": slide_title,
        "metric_id": metric_id,
        "value_format": value_format,
        "min_visual_rows": int((project.get("render") or {}).get("min_visual_rows", 4)),
        "visual_asset": str(visual_path),
        "visual_metadata": str(metadata_path),
        "visual_manifest": str(visual_manifest_path),
        "readability": visual_manifest.get("readability") or {},
        "warnings": visual_manifest.get("warnings") or [],
    }


def _qa_party(
    *,
    party: dict[str, Any],
    slide_paths: list[Path],
    visuals: dict[str, dict[str, Any]],
    cover: dict[str, Any],
    project: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    expected_titles = {
        2: "Most Discussed Issues",
        3: "Issues Discussed More Than Average",
        4: "Issues Discussed More Than Average per TD",
    }
    short_chart_max = round((1210 * horizontal_bar.PLOT_HEIGHT / 4) * 0.72, 2)
    for slide_no, path in enumerate(slide_paths, start=1):
        with Image.open(path) as image:
            dimensions_ok = image.size == (W, H)
        checks: dict[str, Any] = {"dimensions_ok": dimensions_ok}
        if slide_no == 1:
            geometry = cover["logo_geometry"]
            checks.update(
                {
                    "cover_title_ok": cover["cover_title"] == "Party Speech Breakdown",
                    "featured_issue_ok": bool(cover.get("featured_issue")) and cover.get("featured_issue") == ((party.get("raw_counts") or [{}])[0].get("label") if party.get("raw_counts") else "No dominant issue identified"),
                    "logo_size_ok": geometry["square_size"] == [500, 500],
                    "logo_top_ok": geometry["top"] == 300,
                    "logo_centered_ok": geometry["centered"] is True,
                    "logo_border_ok": geometry["border"] == {"enabled": True, "color": "#d8b45f", "width_px": 6, "position": "inside_square"},
                    "asset_registry_ok": ASSET_REGISTRY_PATH == str((project.get("qa") or {}).get("require_asset_registry")),
                    "canonical_asset_uri_ok": str((cover.get("party_asset") or {}).get("logo_s3_uri", "")).startswith(
                        f"s3://eirepolitic-data/processed/reference/party_assets/v1/assets/{party['party_key']}/"
                    ),
                }
            )
        elif slide_no in expected_titles:
            key = {2: "most_discussed_issues", 3: "more_than_average", 4: "more_per_td"}[slide_no]
            meta = visuals[key]
            readability = meta.get("readability") or {}
            displayed = int(readability.get("displayed_item_count") or 0)
            effective = int(readability.get("effective_visual_row_count") or 0)
            bar_thickness = float(readability.get("bar_thickness_px") or 0.0)
            checks.update(
                {
                    "title_ok": meta["slide_title"] == expected_titles[slide_no],
                    "no_category_clipping": int(readability.get("category_text_clipped_count") or 0) == 0,
                    "no_value_clipping": int(readability.get("value_text_clipped_count") or 0) == 0,
                    "no_label_truncation": int(readability.get("truncated_label_count") or 0) == 0,
                    "min_visual_rows_ok": int(readability.get("min_visual_rows") or 0) == 4,
                    "short_chart_virtual_rows_ok": displayed == 0 or displayed >= 4 or effective == 4,
                    "short_chart_bar_thickness_ok": displayed == 0 or displayed >= 4 or bar_thickness <= short_chart_max + 0.01,
                    "empty_state_truthful": displayed > 0 or bool(readability.get("empty_message")),
                    "value_format_ok": meta["value_format"] in {"integer", "plus_pp_1", "plus_per_td_2"},
                }
            )
        else:
            checks["glossary_present"] = path.name == "05_glossary.png" and path.stat().st_size > 0
        status = "PASS" if all(bool(value) for value in checks.values()) else "FAIL"
        rows.append(
            {
                "party": party["party"],
                "party_key": party["party_key"],
                "slide": slide_no,
                "path": str(path),
                "status": status,
                **checks,
            }
        )
    return rows


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    period = resolve_period(period_spec)
    require_completed_calendar_month(period)
    period_key = period.start.strftime("%Y-%m")
    expected_party_count = int((project.get("qa") or {}).get("expected_party_count", 11))
    expected_slide_count = int((project.get("qa") or {}).get("expected_slide_count", 55))

    s3 = boto3.client("s3", region_name="ca-central-1")
    batch = resolve_validated_production_batch(s3=s3)
    required_tables = [str(value) for value in ((project.get("source") or {}).get("required_tables") or [])]
    frames, source_lineage = load_csv_tables(batch, required_tables, s3=s3)
    parties, readiness = _prepare_metrics(frames, period=period, expected_party_count=expected_party_count)

    period_root = output_root / f"period={period_key}"
    if period_root.exists():
        # Re-generation is deterministic from source lineage, but stale files from a
        # previous failed attempt must never leak into the new package.
        import shutil
        shutil.rmtree(period_root)
    period_root.mkdir(parents=True, exist_ok=True)

    slide_defs = {str(item["id"]): item for item in project.get("slides", {}).get("definitions", [])}
    qa_rows: list[dict[str, Any]] = []
    party_manifests: list[dict[str, Any]] = []
    covers, most, more_avg, more_td, carousels = [], [], [], [], []

    for party in parties:
        party_root = period_root / "parties" / party["party_key"]
        slides_dir = party_root / "slides"
        paths = [
            slides_dir / "01_cover.png",
            slides_dir / "02_most_discussed_issues.png",
            slides_dir / "03_more_than_average.png",
            slides_dir / "04_more_per_td.png",
            slides_dir / "05_glossary.png",
        ]
        cover_lineage = _render_cover(paths[0], party=party, period=period, project=project, s3=s3)
        visuals = {
            "most_discussed_issues": _render_analytical(
                paths[1], party=party, period=period, project=project, rows=party["raw_counts"],
                slide_id="most_discussed_issues", slide_title=str(slide_defs["most_discussed_issues"]["title"]),
                metric_id="raw_counts", value_format=str(slide_defs["most_discussed_issues"]["value_format"]), source_batch_id=batch.batch_id,
            ),
            "more_than_average": _render_analytical(
                paths[2], party=party, period=period, project=project, rows=party["share_vs_average"],
                slide_id="more_than_average", slide_title=str(slide_defs["more_than_average"]["title"]),
                metric_id="share_vs_average", value_format=str(slide_defs["more_than_average"]["value_format"]), source_batch_id=batch.batch_id,
            ),
            "more_per_td": _render_analytical(
                paths[3], party=party, period=period, project=project, rows=party["per_td_vs_average"],
                slide_id="more_per_td", slide_title=str(slide_defs["more_per_td"]["title"]),
                metric_id="per_td_vs_average", value_format=str(slide_defs["more_per_td"]["value_format"]), source_batch_id=batch.batch_id,
            ),
        }
        glossary_meta = draw_glossary(GLOSSARY, paths[4])
        party_qa = _qa_party(party=party, slide_paths=paths, visuals=visuals, cover=cover_lineage, project=project)
        qa_rows.extend(party_qa)

        manifest = {
            "project_id": PROJECT_ID,
            "period": period_key,
            "party": party["party"],
            "display_party_name": party["display_party_name"],
            "party_key": party["party_key"],
            "party_uri": party["party_uri"],
            "td_count": party["td_count"],
            "classified_speeches": party["classified_speeches"],
            "avg_speeches_per_td": round(float(party["avg_speeches_per_td"]), 4),
            "raw_counts": party["raw_counts"],
            "share_vs_average": party["share_vs_average"],
            "per_td_vs_average": party["per_td_vs_average"],
            "party_asset_registry": ASSET_REGISTRY_PATH,
            **cover_lineage,
            "analytical_visuals": visuals,
            "glossary_terms": [term for term, _ in GLOSSARY],
            "glossary_render": glossary_meta,
            "slides": [str(path.relative_to(period_root)) for path in paths],
            "qa": {"passed": sum(row["status"] == "PASS" for row in party_qa), "failed": sum(row["status"] != "PASS" for row in party_qa)},
            "review_state": "pending_human_review",
            "publication_enabled": False,
        }
        (party_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        party_manifests.append(manifest)
        display = party["display_party_name"]
        covers.append((display, paths[0])); most.append((display, paths[1])); more_avg.append((display, paths[2])); more_td.append((display, paths[3])); carousels.append((display, paths))

    if len(parties) != expected_party_count:
        raise RuntimeError(f"Expected {expected_party_count} parties, got {len(parties)}")
    if len(qa_rows) != expected_slide_count:
        raise RuntimeError(f"Expected {expected_slide_count} QA slide rows, got {len(qa_rows)}")
    failed = [row for row in qa_rows if row["status"] != "PASS"]
    if failed:
        raise RuntimeError(f"Rendered-slide QA failed for {len(failed)} slides: {failed[:5]}")

    contacts = period_root / "contact_sheets"
    contact_sheet(covers, contacts / "covers.jpg")
    contact_sheet(most, contacts / "most_discussed_issues.jpg")
    contact_sheet(more_avg, contacts / "more_than_average.jpg")
    contact_sheet(more_td, contacts / "more_per_td.jpg")
    carousel_sheet(carousels, contacts / "five_slide_overview.jpg")

    qa_path = period_root / "qa_summary.csv"
    all_keys = sorted({key for row in qa_rows for key in row})
    with qa_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(qa_rows)

    max_short_thickness = round((1210 * horizontal_bar.PLOT_HEIGHT / 4) * 0.72, 2)
    run_manifest = {
        "project_id": PROJECT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "period": {"key": period_key, "start": period.start.isoformat(), "end": period.end.isoformat(), "label": _period_label(period)},
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "source_batch_manifest_key": batch.pointer.get("manifest_key"),
        "source_batch_status": batch.manifest.get("status"),
        "sources": source_lineage,
        "readiness": readiness,
        "calculation": {
            "speech_attribution": "event-date Dáil membership and party history",
            "raw_counts": "distinct policy-classified speeches by party and issue in period; top 7",
            "share_vs_average": "party issue share minus unweighted mean issue share across all displayed period-end groups, including zero shares; positive top 7",
            "per_td_denominator": "active Dáil TDs in party/group at period end",
            "per_td_vs_average": "party issue speeches per period-end TD minus unweighted mean rate across all displayed groups, including zero rates; positive top 7",
        },
        "presentation_labels": str(LABELS_PATH),
        "party_asset_registry": ASSET_REGISTRY_PATH,
        "party_display_aliases": {"Independent": "Independents"},
        "analytical_visual_source": APPROVED_VARIANT_SOURCE,
        "chart_geometry": {
            "outer_slide_dimensions": [W, H],
            "visual_media_dimensions": [1032, 1210],
            "min_visual_rows": 4,
            "max_short_chart_bar_thickness_px": max_short_thickness,
            "short_chart_bar_thickness_policy": "1-3 row charts use a centered virtual 4-row stack",
        },
        "cover_logo_geometry": {
            "square_size": [500, 500], "top": 300, "centered": True,
            "border": {"enabled": True, "color": "#d8b45f", "width_px": 6, "position": "inside_square"},
            "artwork_scale_overrides": {"fine-gael": 1.10, "labour-party": 1.10, "independent-ireland": 1.10},
        },
        "analytical_titles": {
            "most_discussed_issues": "Most Discussed Issues",
            "more_than_average": "Issues Discussed More Than Average",
            "more_per_td": "Issues Discussed More Than Average per TD",
        },
        "glossary_terms": [term for term, _ in GLOSSARY],
        "parties": party_manifests,
        "qa": {"slide_count": len(qa_rows), "passed": len(qa_rows), "failed": 0, "party_count": len(parties)},
        "review_state": "pending_human_review",
        "publication_enabled": False,
    }
    manifest_path = period_root / "run_manifest.json"
    manifest_path.write_text(json.dumps(run_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    zip_prefix = str((project.get("output") or {}).get("zip_prefix") or "instagram-post")
    zip_name = f"{zip_prefix}-{period.start.strftime('%B').lower()}-{period.start.year}.zip"
    zip_path = output_root / zip_name
    package_manifest = deterministic_zip(period_root, zip_path)

    return {
        "status": "PASS",
        "project_id": PROJECT_ID,
        "period": period_key,
        "source_batch_id": batch.batch_id,
        "party_count": len(parties),
        "slide_count": len(qa_rows),
        "qa": {"passed": len(qa_rows), "failed": 0},
        "output_root": str(period_root),
        "zip_path": str(zip_path),
        "zip_sha256": package_manifest["sha256"],
        "contact_sheets": {
            "five_slide_overview": str(contacts / "five_slide_overview.jpg"),
            "most_discussed_issues": str(contacts / "most_discussed_issues.jpg"),
            "more_than_average": str(contacts / "more_than_average.jpg"),
            "more_per_td": str(contacts / "more_per_td.jpg"),
        },
        "review_state": "pending_human_review",
        "publication_enabled": False,
    }
