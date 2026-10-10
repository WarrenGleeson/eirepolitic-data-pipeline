"""Translate project-specific adapter results into the generic RenderResult contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from instagram.factory.contract import ContactSheetRef, QASummary, RenderResult, SlideRef


def _normalize_party_issue_monthly_profile_v2(project: dict[str, Any], raw: dict[str, Any], *, output_root: Path) -> RenderResult:
    render_cfg = project.get("render") or {}
    width = int(render_cfg.get("width", 1080)); height = int(render_cfg.get("height", 1350))
    period_root = Path(raw["output_root"])
    run_manifest_path = period_root / "run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    slides = []
    for party_manifest in run_manifest.get("parties", []):
        party_key = str(party_manifest["party_key"])
        for relative_slide_path in party_manifest.get("slides", []):
            slides.append(SlideRef(id=f"{party_key}/{Path(str(relative_slide_path)).stem}", path=str(period_root / str(relative_slide_path)), width=width, height=height))
    contact_sheets = tuple(ContactSheetRef(id=str(k), path=str(v)) for k, v in (raw.get("contact_sheets") or {}).items())
    declared_qa = project.get("qa") or {}
    expected = int(declared_qa.get("expected_slide_count", raw.get("slide_count", len(slides))))
    package = {"zip_path": raw["zip_path"], "sha256": raw.get("zip_sha256")} if raw.get("zip_path") else None
    return RenderResult(project_id=str(raw["project_id"]), period_key=str(raw["period"]), output_root=str(period_root), slides=tuple(slides), contact_sheets=contact_sheets, caption_path=None, manifest_path=str(run_manifest_path), package=package, qa=QASummary(expected_slide_count=expected, actual_slide_count=int(raw.get("slide_count", len(slides))), dimensions=(width, height)), review_state=str(raw["review_state"]), publication_enabled=raw["publication_enabled"], source_batch_id=raw.get("source_batch_id"), raw={**raw, "run_manifest": run_manifest})


def _normalize_ipi_polling_factory_v1(project: dict[str, Any], raw: dict[str, Any], *, output_root: Path) -> RenderResult:
    qa_block = raw.get("qa") or {}; dims = qa_block.get("dimensions")
    width = int(dims[0]) if dims else None; height = int(dims[1]) if dims else None
    slide_paths = [str(path) for path in (raw.get("slides") or [])]
    definition_ids = [str(item["id"]) for item in (project.get("slides") or {}).get("definitions", [])]
    slides = tuple(SlideRef(id=(definition_ids[i] if i < len(definition_ids) else Path(path).stem), path=path, width=width, height=height) for i, path in enumerate(slide_paths))
    contact_sheet_path = raw.get("contact_sheet")
    contact_sheets = (ContactSheetRef(id="four_slide_overview", path=str(contact_sheet_path)),) if contact_sheet_path else ()
    if slide_paths:
        period_root = Path(slide_paths[0]).parent.parent
        candidate_manifest = period_root / "metadata" / "manifest.json"
        manifest_path = str(candidate_manifest) if candidate_manifest.exists() else None; output_root_str = str(period_root)
    else:
        manifest_path = None; output_root_str = str(output_root)
    expected = int(qa_block.get("expected_slide_count", len(slide_paths)))
    return RenderResult(project_id=str(raw.get("project_id", project.get("project_id"))), period_key=str((raw.get("latest_poll") or {}).get("publication_date") or "unknown"), output_root=output_root_str, slides=slides, contact_sheets=contact_sheets, caption_path=raw.get("caption"), manifest_path=manifest_path, package=raw.get("package"), qa=QASummary(expected_slide_count=expected, actual_slide_count=int(qa_block.get("actual_slide_count", len(slide_paths))), dimensions=(width, height) if width and height else None), review_state=str(raw["review_state"]), publication_enabled=raw["publication_enabled"], source_batch_id=None, raw=raw)


def _period_expected(value: Any, period_key: str, fallback: int) -> int:
    if isinstance(value, dict):
        resolved = value.get(period_key)
        return fallback if resolved is None else int(resolved)
    if value is None:
        return fallback
    return int(value)


def _normalize_bill_tracker_factory_v1(project: dict[str, Any], raw: dict[str, Any], *, output_root: Path) -> RenderResult:
    qa_block = raw.get("qa") or {}; dims = qa_block.get("dimensions") or (1080, 1350)
    width, height = int(dims[0]), int(dims[1])
    slide_paths = [str(path) for path in (raw.get("slides") or [])]
    slides = tuple(SlideRef(id=Path(path).stem, path=path, width=width, height=height) for path in slide_paths)
    contacts = tuple(ContactSheetRef(id=str(k), path=str(v)) for k, v in (raw.get("contact_sheets") or {}).items())
    period_root = Path(slide_paths[0]).parent.parent if slide_paths else Path(output_root)
    candidate_manifest = period_root / "metadata" / "manifest.json"
    period_key = str(raw.get("period_key") or "unknown")
    declared = (project.get("qa") or {}).get("expected_slide_count")
    expected = int(qa_block.get("expected_slide_count", _period_expected(declared, period_key, len(slide_paths))))
    return RenderResult(
        project_id=str(raw.get("project_id") or project.get("project_id")),
        period_key=period_key,
        output_root=str(period_root),
        slides=slides,
        contact_sheets=contacts,
        caption_path=raw.get("caption"),
        manifest_path=str(candidate_manifest) if candidate_manifest.exists() else None,
        package=raw.get("package"),
        qa=QASummary(expected_slide_count=expected, actual_slide_count=int(qa_block.get("actual_slide_count", len(slides))), dimensions=(width, height)),
        review_state=str(raw["review_state"]),
        publication_enabled=raw["publication_enabled"],
        source_batch_id=raw.get("source_batch_id"),
        raw=raw,
    )


NORMALIZERS: dict[str, Callable[..., RenderResult]] = {
    "party_issue_monthly_profile_v2": _normalize_party_issue_monthly_profile_v2,
    "ipi_polling_factory_v1": _normalize_ipi_polling_factory_v1,
    "bill_tracker_factory_v1": _normalize_bill_tracker_factory_v1,
}


def normalize_result(project: dict[str, Any], raw: dict[str, Any], *, output_root: Path) -> RenderResult:
    project_id = str(project.get("project_id") or raw.get("project_id") or "")
    shim = NORMALIZERS.get(project_id)
    if shim is None:
        raise RuntimeError(f"No normalize_result() shim registered for project_id={project_id!r} in instagram/factory/normalize.py")
    return shim(project, raw, output_root=output_root)
