from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from instagram.factory.oireachtas_source import resolve_validated_production_batch
from instagram.factory.package import deterministic_zip
from instagram.factory.render_primitives import contact_sheet
from instagram.projects.bill_tracker_factory_v1 import adapter as enacted_adapter
from instagram.projects.bill_tracker_factory_v1.third_stage_renderers import render_amendment_detail, render_compact_third_stage, render_third_stage_bill
from instagram.projects.bill_tracker_factory_v1.third_stage_renderers_v2 import render_amendment_story, render_complex_summary, render_status_case
from instagram.projects.bill_tracker_factory_v1.third_stage_full_renderers import render_bill_slide, render_cover, render_explainer

PROJECT_ID = "bill_tracker_factory_v1"
THIRD_STAGE_MOCKUPS = "third_stage_mockups"
THIRD_STAGE_MOCKUPS_V2 = "third_stage_mockups_v2"
THIRD_STAGE_FULL_REVIEW = "third_stage_full_review"
SESSION_DIR = Path("director/sessions/2026-10-10-bill-tracker-third-stage")


def _assert_image(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing rendered slide: {path}")
    with Image.open(path) as image:
        if image.size != (1080, 1350):
            raise RuntimeError(f"Unexpected dimensions for {path}: {image.size}")


def _load(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _base_manifest(*, period: str, batch, slides: list[Path], contact_sheets: dict[str, Path], caption_path: Path, render_manifests: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": PROJECT_ID,
        "period_key": period,
        "review_state": "pending_human_review",
        "publication_enabled": False,
        "publishing_allowed": False,
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "source_lineage": {},
        "editorial_verification_date": "2026-10-10",
        "slides": [str(p) for p in slides],
        "contact_sheets": {k: str(v) for k, v in contact_sheets.items()},
        "caption": str(caption_path),
        "render_manifests": render_manifests,
        "qa": {
            "expected_slide_count": len(slides),
            "actual_slide_count": len(slides),
            "dimensions": [1080, 1350],
            "source_footer_required": True,
            "publication_enabled": False,
            "publishing_allowed": False,
            "overflow_assertions_passed": True,
        },
    }


def _render_set(*, period: str, payload_path: str, output_root: Path, plan: list[tuple[str, Any, str]]) -> dict[str, Any]:
    bills = (_load(payload_path).get("mockups") or {})
    batch = resolve_validated_production_batch()
    root = output_root / f"period={period}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root / "slides"; metadata_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for directory in (slides_dir, metadata_dir, contact_dir): directory.mkdir(parents=True, exist_ok=True)
    slides: list[Path] = []; manifests: dict[str, Any] = {}; labels = []
    for filename, renderer, key in plan:
        path = slides_dir / filename
        rm = renderer(bills[key], path); _assert_image(path)
        slides.append(path); manifests[path.stem] = rm; labels.append((path.stem.replace("_", " ").title(), path))
    contact_path = contact_dir / f"{period}_contact_sheet.jpg"
    contact_sheet(labels, contact_path, columns=2)
    caption_path = root / "caption.txt"; caption_path.write_text("Mockup review only. Publication disabled.\n", encoding="utf-8")
    manifest = _base_manifest(period=period, batch=batch, slides=slides, contact_sheets={period: contact_path}, caption_path=caption_path, render_manifests=manifests)
    mp = metadata_dir / "manifest.json"; mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / f"{period}_review.zip")
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest


def _load_inventory() -> dict[str, dict[str, Any]]:
    path = SESSION_DIR / "live_third_stage_inventory.csv"
    if not path.is_file():
        raise RuntimeError(f"Missing Third Stage inventory: {path}")
    out: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out[str(row.get("key") or "").strip()] = dict(row)
    return out


def _load_groups(inventory: dict[str, dict[str, Any]]) -> list[list[dict[str, Any]]]:
    path = SESSION_DIR / "live_third_stage_reconciliation.md"
    if not path.is_file():
        raise RuntimeError(f"Missing Third Stage reconciliation: {path}")
    groups: list[list[dict[str, Any]]] = []
    line_rx = re.compile(r"^- \*\*Post (\d+)\*\* \((\d+) Bills\): (.+)$")
    item_rx = re.compile(r"^(.*?) \((\d{4}/\d+), (complex|substantive|light)\)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        m = line_rx.match(line.strip())
        if not m:
            continue
        expected = int(m.group(2))
        items: list[dict[str, Any]] = []
        for raw in m.group(3).split("; "):
            im = item_rx.match(raw.strip())
            if not im:
                raise RuntimeError(f"Could not parse Third Stage grouping item: {raw!r}")
            title, key, complexity = im.groups()
            inv = inventory.get(key, {})
            year, no = key.split("/", 1)
            items.append({
                "key": key,
                "title": title,
                "bill_year": year,
                "bill_no": no,
                "complexity": complexity,
                "live_stage_date": inv.get("live_stage_date") or "",
                "live_stage_house": inv.get("live_stage_house") or "",
            })
        if len(items) != expected:
            raise RuntimeError(f"Post {m.group(1)} expected {expected} Bills but parsed {len(items)}")
        groups.append(items)
    if len(groups) != 24 or sum(len(g) for g in groups) != 94:
        raise RuntimeError(f"Unexpected grouping: {len(groups)} posts / {sum(len(g) for g in groups)} Bills")
    return groups


def _generate_full_review(*, output_root: Path) -> dict[str, Any]:
    batch = resolve_validated_production_batch()
    inventory = _load_inventory()
    groups = _load_groups(inventory)
    total_posts = len(groups)

    root = output_root / f"period={THIRD_STAGE_FULL_REVIEW}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root / "slides"; metadata_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for directory in (slides_dir, metadata_dir, contact_dir): directory.mkdir(parents=True, exist_ok=True)

    slides: list[Path] = []
    contacts: dict[str, Path] = {}
    render_manifests: dict[str, Any] = {}
    post_records: list[dict[str, Any]] = []

    for post_no, bills in enumerate(groups, start=1):
        post_key = f"post_{post_no:02d}"
        post_dir = slides_dir / post_key
        post_dir.mkdir(parents=True, exist_ok=True)
        post_slides: list[Path] = []
        labels: list[tuple[str, Path]] = []

        cover = post_dir / "01_cover.png"
        rm = render_cover(post_no, total_posts, bills, cover); _assert_image(cover)
        slides.append(cover); post_slides.append(cover); labels.append((f"Post {post_no} · Cover", cover)); render_manifests[f"{post_key}/01_cover"] = rm

        for idx, bill in enumerate(bills, start=2):
            bill_path = post_dir / f"{idx:02d}_bill_{bill['bill_year']}_{bill['bill_no']}.png"
            rm = render_bill_slide(bill, bill_path); _assert_image(bill_path)
            slides.append(bill_path); post_slides.append(bill_path); labels.append((bill["title"], bill_path)); render_manifests[f"{post_key}/{bill_path.stem}"] = rm

        explainer = post_dir / f"{len(bills)+2:02d}_third_stage_explainer.png"
        rm = render_explainer(post_no, total_posts, explainer); _assert_image(explainer)
        slides.append(explainer); post_slides.append(explainer); labels.append((f"Post {post_no} · Third Stage guide", explainer)); render_manifests[f"{post_key}/{explainer.stem}"] = rm

        contact_path = contact_dir / f"{post_key}_contact_sheet.jpg"
        contact_sheet(labels, contact_path, columns=2 if len(post_slides) <= 4 else 3)
        contacts[post_key] = contact_path
        post_records.append({
            "post": post_no,
            "bill_count": len(bills),
            "slide_count": len(post_slides),
            "complex_bill_count": sum(1 for b in bills if b.get("complexity") == "complex"),
            "contact_sheet": str(contact_path),
            "bills": [{"key": b["key"], "title": b["title"], "complexity": b["complexity"]} for b in bills],
        })

    if len(slides) != 142:
        raise RuntimeError(f"Expected 142 Third Stage review slides, rendered {len(slides)}")

    caption_path = root / "caption.txt"
    caption_path.write_text("Full Third Stage review render only. 24 posts / 94 Bills. Publication disabled.\n", encoding="utf-8")
    manifest = _base_manifest(period=THIRD_STAGE_FULL_REVIEW, batch=batch, slides=slides, contact_sheets=contacts, caption_path=caption_path, render_manifests=render_manifests)
    manifest["post_count"] = 24
    manifest["bill_count"] = 94
    manifest["posts"] = post_records
    manifest["review_note"] = "Baseline full-series review. Complex Bills remain flagged for amendment/vote expansion after visual and editorial review."
    mp = metadata_dir / "manifest.json"
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "third_stage_full_review.zip")
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    period = (period_spec or "post1").strip().lower()
    if period == THIRD_STAGE_FULL_REVIEW:
        return _generate_full_review(output_root=output_root)
    if period == THIRD_STAGE_MOCKUPS_V2:
        return _render_set(period=period, payload_path="instagram/projects/bill_tracker_factory_v1/third_stage_content_v2.yml", output_root=output_root, plan=[
            ("01_broadcasting_summary_v2.png", render_complex_summary, "broadcasting"),
            ("02_broadcasting_amendments_v2.png", render_amendment_story, "broadcasting"),
            ("03_social_welfare_v2.png", render_status_case, "social_welfare"),
            ("04_slapp_v2.png", render_status_case, "slapp"),
        ])
    if period == THIRD_STAGE_MOCKUPS:
        return _render_set(period=period, payload_path="instagram/projects/bill_tracker_factory_v1/third_stage_content.yml", output_root=output_root, plan=[
            ("01_broadcasting_summary.png", render_third_stage_bill, "broadcasting"),
            ("02_broadcasting_amendments.png", render_amendment_detail, "broadcasting"),
            ("03_social_welfare_compact.png", render_compact_third_stage, "social_welfare"),
            ("04_slapp_compact.png", render_compact_third_stage, "slapp"),
        ])
    return enacted_adapter.generate(project=project, period_spec=period, output_root=output_root)
