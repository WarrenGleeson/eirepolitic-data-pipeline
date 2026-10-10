from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw

from instagram.factory.oireachtas_source import resolve_validated_production_batch
from instagram.factory.package import deterministic_zip
from instagram.factory.render_primitives import TEXT, base_slide, contact_sheet, font
from instagram.projects.bill_tracker_factory_v1 import adapter as enacted_adapter
from instagram.projects.bill_tracker_factory_v1.third_stage_renderers import render_third_stage_bill

PROJECT_ID = "bill_tracker_factory_v1"
THIRD_STAGE_PROTOTYPE = "third_stage_prototype"


def _assert_image(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing rendered slide: {path}")
    with Image.open(path) as image:
        if image.size != (1080, 1350):
            raise RuntimeError(f"Unexpected dimensions for {path}: {image.size}")


def _load_payload() -> dict[str, Any]:
    return yaml.safe_load(Path("instagram/projects/bill_tracker_factory_v1/third_stage_content.yml").read_text(encoding="utf-8")) or {}


def _generate_third_stage_prototype(*, output_root: Path) -> dict[str, Any]:
    payload = _load_payload(); bill = (payload.get("prototype") or {}).get("bill") or {}
    if not bill:
        raise RuntimeError("Third Stage prototype content is missing its Bill payload")
    batch = resolve_validated_production_batch()
    root = output_root / f"period={THIRD_STAGE_PROTOTYPE}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root / "slides"; metadata_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for directory in (slides_dir, metadata_dir, contact_dir): directory.mkdir(parents=True, exist_ok=True)
    slide = slides_dir / "01_broadcasting_third_stage.png"
    diagnostic = None
    try:
        render_manifest = render_third_stage_bill(bill, slide)
    except Exception as exc:
        diagnostic = f"{type(exc).__name__}: {exc}"
        im = base_slide(); draw = ImageDraw.Draw(im)
        draw.text((540, 160), "THIRD STAGE RENDER DIAGNOSTIC", font=font(28, True), fill=TEXT, anchor="ma")
        draw.text((80, 300), diagnostic[:900], font=font(16), fill=TEXT, anchor="la")
        im.save(slide)
        render_manifest = {"renderer": "diagnostic", "warnings": [diagnostic], "source_footer": True}
    _assert_image(slide)
    contact_path = contact_dir / "third_stage_prototype_contact_sheet.jpg"
    contact_sheet([("Broadcasting · Third Stage", slide)], contact_path, columns=1)
    caption_path = root / "caption.txt"
    caption_path.write_text((f"DIAGNOSTIC: {diagnostic}\n" if diagnostic else "Prototype only. Publication disabled.\n"), encoding="utf-8")
    manifest = {
        "project_id": PROJECT_ID,
        "period_key": THIRD_STAGE_PROTOTYPE,
        "review_state": "pending_human_review",
        "publication_enabled": False,
        "publishing_allowed": False,
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "source_lineage": {},
        "production_snapshot_gaps": ["Bill 54/2026 is absent from the validated production Current Committee Stage inventory; official live Oireachtas records were used as editorial truth."],
        "editorial_verification_date": "2026-10-10",
        "editorial_sources": bill.get("sources") or [],
        "slides": [str(slide)],
        "contact_sheets": {THIRD_STAGE_PROTOTYPE: str(contact_path)},
        "caption": str(caption_path),
        "render_manifests": {slide.stem: render_manifest},
        "qa": {"expected_slide_count": 1, "actual_slide_count": 1, "dimensions": [1080, 1350], "source_footer_required": True, "publication_enabled": False, "publishing_allowed": False, "overflow_assertions_passed": diagnostic is None},
    }
    manifest_path = metadata_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "bill_tracker_third_stage_prototype_review.zip")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    period = (period_spec or "post1").strip().lower()
    if period == THIRD_STAGE_PROTOTYPE:
        return _generate_third_stage_prototype(output_root=output_root)
    return enacted_adapter.generate(project=project, period_spec=period, output_root=output_root)
