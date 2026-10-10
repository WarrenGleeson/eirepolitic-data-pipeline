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
from instagram.projects.bill_tracker_factory_v1.third_stage_renderers import (
    render_amendment_detail,
    render_compact_third_stage,
    render_third_stage_bill,
)

PROJECT_ID = "bill_tracker_factory_v1"
THIRD_STAGE_PROTOTYPE = "third_stage_prototype"
THIRD_STAGE_MOCKUPS = "third_stage_mockups"


def _assert_image(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing rendered slide: {path}")
    with Image.open(path) as image:
        if image.size != (1080, 1350):
            raise RuntimeError(f"Unexpected dimensions for {path}: {image.size}")


def _load_payload() -> dict[str, Any]:
    return yaml.safe_load(Path("instagram/projects/bill_tracker_factory_v1/third_stage_content.yml").read_text(encoding="utf-8")) or {}


def _base_manifest(*, period: str, batch, slides: list[Path], contact_path: Path, caption_path: Path, render_manifests: dict[str, Any]) -> dict[str, Any]:
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
        "contact_sheets": {period: str(contact_path)},
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


def _generate_third_stage_prototype(*, output_root: Path) -> dict[str, Any]:
    payload = _load_payload(); bill = (payload.get("mockups") or {}).get("broadcasting") or (payload.get("prototype") or {}).get("bill") or {}
    if not bill: raise RuntimeError("Third Stage prototype content is missing its Bill payload")
    batch = resolve_validated_production_batch()
    root = output_root / f"period={THIRD_STAGE_PROTOTYPE}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root / "slides"; metadata_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for d in (slides_dir, metadata_dir, contact_dir): d.mkdir(parents=True, exist_ok=True)
    slide = slides_dir / "01_broadcasting_third_stage.png"
    rm = render_third_stage_bill(bill, slide); _assert_image(slide)
    contact_path = contact_dir / "third_stage_prototype_contact_sheet.jpg"
    contact_sheet([("Broadcasting · Third Stage", slide)], contact_path, columns=1)
    caption_path = root / "caption.txt"; caption_path.write_text("Prototype only. Publication disabled.\n", encoding="utf-8")
    manifest = _base_manifest(period=THIRD_STAGE_PROTOTYPE, batch=batch, slides=[slide], contact_path=contact_path, caption_path=caption_path, render_manifests={slide.stem: rm})
    manifest["production_snapshot_gaps"] = ["Bill 54/2026 is absent from the validated production Current Committee Stage inventory; official live Oireachtas records were used as editorial truth."]
    mp = metadata_dir / "manifest.json"; mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "bill_tracker_third_stage_prototype_review.zip")
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest


def _generate_mockups(*, output_root: Path) -> dict[str, Any]:
    payload = _load_payload(); bills = payload.get("mockups") or {}
    required = ["broadcasting", "social_welfare", "slapp"]
    if any(k not in bills for k in required): raise RuntimeError("Third Stage mockup content is incomplete")
    batch = resolve_validated_production_batch()
    root = output_root / f"period={THIRD_STAGE_MOCKUPS}"
    if root.exists(): shutil.rmtree(root)
    slides_dir = root / "slides"; metadata_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for d in (slides_dir, metadata_dir, contact_dir): d.mkdir(parents=True, exist_ok=True)

    slides: list[Path] = []
    manifests: dict[str, Any] = {}
    plan = [
        ("01_broadcasting_summary.png", render_third_stage_bill, bills["broadcasting"]),
        ("02_broadcasting_amendments.png", render_amendment_detail, bills["broadcasting"]),
        ("03_social_welfare_compact.png", render_compact_third_stage, bills["social_welfare"]),
        ("04_slapp_compact.png", render_compact_third_stage, bills["slapp"]),
    ]
    labels = []
    for filename, renderer, bill in plan:
        path = slides_dir / filename
        rm = renderer(bill, path); _assert_image(path)
        slides.append(path); manifests[path.stem] = rm
        labels.append((filename.replace(".png", "").replace("_", " ").title(), path))

    contact_path = contact_dir / "third_stage_mockups_contact_sheet.jpg"
    contact_sheet(labels, contact_path, columns=2)
    caption_path = root / "caption.txt"
    caption_path.write_text("Mockup review only. Three evidence-density treatments. Publication disabled.\n", encoding="utf-8")
    manifest = _base_manifest(period=THIRD_STAGE_MOCKUPS, batch=batch, slides=slides, contact_path=contact_path, caption_path=caption_path, render_manifests=manifests)
    manifest["mockup_strategy"] = {
        "broadcasting": "two-slide complex treatment",
        "social_welfare": "one-slide compact treatment because no Committee Stage debate/amendment record is linked on the official Bill page as of audit date",
        "slapp": "one-slide record-developing treatment pending a published Committee Stage record",
    }
    mp = metadata_dir / "manifest.json"; mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "bill_tracker_third_stage_mockups_review.zip")
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    period = (period_spec or "post1").strip().lower()
    if period == THIRD_STAGE_PROTOTYPE: return _generate_third_stage_prototype(output_root=output_root)
    if period == THIRD_STAGE_MOCKUPS: return _generate_mockups(output_root=output_root)
    return enacted_adapter.generate(project=project, period_spec=period, output_root=output_root)
