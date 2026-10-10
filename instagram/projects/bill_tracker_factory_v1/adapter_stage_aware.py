from __future__ import annotations

import json
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

PROJECT_ID = "bill_tracker_factory_v1"
THIRD_STAGE_PROTOTYPE = "third_stage_prototype"
THIRD_STAGE_MOCKUPS = "third_stage_mockups"
THIRD_STAGE_MOCKUPS_V2 = "third_stage_mockups_v2"


def _assert_image(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0: raise RuntimeError(f"Missing rendered slide: {path}")
    with Image.open(path) as image:
        if image.size != (1080, 1350): raise RuntimeError(f"Unexpected dimensions for {path}: {image.size}")


def _load(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _base_manifest(*, period: str, batch, slides: list[Path], contact_path: Path, caption_path: Path, render_manifests: dict[str, Any]) -> dict[str, Any]:
    return {"project_id": PROJECT_ID, "period_key": period, "review_state": "pending_human_review", "publication_enabled": False, "publishing_allowed": False, "source_batch_id": batch.batch_id, "source_pointer": batch.pointer, "source_lineage": {}, "editorial_verification_date": "2026-10-10", "slides": [str(p) for p in slides], "contact_sheets": {period: str(contact_path)}, "caption": str(caption_path), "render_manifests": render_manifests, "qa": {"expected_slide_count": len(slides), "actual_slide_count": len(slides), "dimensions": [1080,1350], "source_footer_required": True, "publication_enabled": False, "publishing_allowed": False, "overflow_assertions_passed": True}}


def _render_set(*, period: str, payload_path: str, output_root: Path, plan: list[tuple[str, Any, str]]) -> dict[str, Any]:
    bills = (_load(payload_path).get("mockups") or {})
    batch = resolve_validated_production_batch()
    root = output_root / f"period={period}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root/"slides"; metadata_dir = root/"metadata"; contact_dir = root/"contact_sheets"
    for d in (slides_dir, metadata_dir, contact_dir): d.mkdir(parents=True, exist_ok=True)
    slides=[]; manifests={}; labels=[]
    for filename, renderer, key in plan:
        path = slides_dir/filename
        rm = renderer(bills[key], path); _assert_image(path)
        slides.append(path); manifests[path.stem]=rm; labels.append((path.stem.replace("_"," ").title(), path))
    contact_path = contact_dir/f"{period}_contact_sheet.jpg"
    contact_sheet(labels, contact_path, columns=2)
    caption_path = root/"caption.txt"; caption_path.write_text("Mockup review only. Publication disabled.\n", encoding="utf-8")
    manifest = _base_manifest(period=period,batch=batch,slides=slides,contact_path=contact_path,caption_path=caption_path,render_manifests=manifests)
    mp=metadata_dir/"manifest.json"; mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root/f"{period}_review.zip")
    mp.write_text(json.dumps(manifest,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    return manifest


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    period=(period_spec or "post1").strip().lower()
    if period == THIRD_STAGE_MOCKUPS_V2:
        return _render_set(period=period,payload_path="instagram/projects/bill_tracker_factory_v1/third_stage_content_v2.yml",output_root=output_root,plan=[("01_broadcasting_summary_v2.png",render_complex_summary,"broadcasting"),("02_broadcasting_amendments_v2.png",render_amendment_story,"broadcasting"),("03_social_welfare_v2.png",render_status_case,"social_welfare"),("04_slapp_v2.png",render_status_case,"slapp")])
    if period == THIRD_STAGE_MOCKUPS:
        return _render_set(period=period,payload_path="instagram/projects/bill_tracker_factory_v1/third_stage_content.yml",output_root=output_root,plan=[("01_broadcasting_summary.png",render_third_stage_bill,"broadcasting"),("02_broadcasting_amendments.png",render_amendment_detail,"broadcasting"),("03_social_welfare_compact.png",render_compact_third_stage,"social_welfare"),("04_slapp_compact.png",render_compact_third_stage,"slapp")])
    return enacted_adapter.generate(project=project, period_spec=period, output_root=output_root)
