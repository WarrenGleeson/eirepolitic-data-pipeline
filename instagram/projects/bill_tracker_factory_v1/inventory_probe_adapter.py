from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import ImageDraw

from instagram.factory.oireachtas_source import load_csv_tables, resolve_validated_production_batch
from instagram.factory.package import deterministic_zip
from instagram.factory.render_primitives import ACCENT, MUTED, TEXT, base_slide, contact_sheet, font

PROJECT_ID = "bill_tracker_factory_v1"
PERIOD = "third_stage_inventory_probe"


def _rows(frame, column, value):
    return frame[frame[column].astype(str).str.strip().eq(value)].copy()


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    batch = resolve_validated_production_batch()
    table_names = [
        "silver_bills", "silver_bill_stages", "silver_bill_sponsors",
        "silver_bill_debates", "silver_speeches", "silver_divisions", "silver_member_votes",
    ]
    frames, lineage = load_csv_tables(batch, table_names)
    bills = frames["silver_bills"]
    stages = frames["silver_bill_stages"]
    sponsors = frames["silver_bill_sponsors"]
    bill_debates = frames["silver_bill_debates"]
    speeches = frames["silver_speeches"]
    divisions = frames["silver_divisions"]
    member_votes = frames["silver_member_votes"]

    current = stages[
        stages["stage_name"].astype(str).str.strip().eq("Committee Stage")
        & stages["stage_outcome"].astype(str).str.strip().str.casefold().eq("current")
    ].copy()
    if "snapshot_date" in current.columns:
        current = current.sort_values(["bill_id", "snapshot_date", "stage_date"]).drop_duplicates("bill_id", keep="last")

    inventory = []
    for _, stage in current.iterrows():
        bill_id = str(stage["bill_id"])
        b = bills[bills["bill_id"].astype(str).eq(bill_id)].copy()
        if not b.empty and "snapshot_date" in b.columns:
            b = b.sort_values("snapshot_date")
        br = b.iloc[-1].to_dict() if not b.empty else {}
        sp = sponsors[sponsors["bill_id"].astype(str).eq(bill_id)] if "bill_id" in sponsors.columns else sponsors.iloc[0:0]
        bd = bill_debates[bill_debates["bill_id"].astype(str).eq(bill_id)] if "bill_id" in bill_debates.columns else bill_debates.iloc[0:0]
        pairs = {(str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) for _, r in bd.iterrows()}
        debate_ids = {p[0] for p in pairs if p[0]}

        linked_speeches = speeches.iloc[0:0]
        if debate_ids and "debate_id" in speeches.columns:
            linked_speeches = speeches[speeches["debate_id"].astype(str).isin(debate_ids)].copy()
            if "debate_section_id" in linked_speeches.columns:
                linked_speeches = linked_speeches[linked_speeches.apply(
                    lambda r: (str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) in pairs, axis=1
                )]

        linked_divisions = divisions.iloc[0:0]
        if debate_ids and "debate_id" in divisions.columns:
            linked_divisions = divisions[divisions["debate_id"].astype(str).isin(debate_ids)].copy()
            if "debate_section_id" in linked_divisions.columns:
                linked_divisions = linked_divisions[linked_divisions.apply(
                    lambda r: (str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) in pairs, axis=1
                )]
        div_ids = set(linked_divisions["division_id"].astype(str)) if "division_id" in linked_divisions.columns else set()
        linked_votes = member_votes[member_votes["division_id"].astype(str).isin(div_ids)] if div_ids and "division_id" in member_votes.columns else member_votes.iloc[0:0]

        inventory.append({
            "bill_id": bill_id,
            "bill_no": br.get("bill_no"),
            "bill_year": br.get("bill_year"),
            "title": br.get("title") or br.get("short_title"),
            "status": br.get("status"),
            "origin_house_name": br.get("origin_house_name"),
            "introduced_date": br.get("introduced_date"),
            "last_event_date": br.get("last_event_date"),
            "stage_name": stage.get("stage_name"),
            "stage_date": stage.get("stage_date"),
            "stage_house_name": stage.get("house_name"),
            "stage_outcome": stage.get("stage_outcome"),
            "stage_snapshot_date": stage.get("snapshot_date"),
            "sponsor_rows": int(len(sp)),
            "bill_debate_rows": int(len(bd)),
            "linked_speech_rows": int(len(linked_speeches)),
            "linked_division_rows": int(len(linked_divisions)),
            "linked_member_vote_rows": int(len(linked_votes)),
            "debates": [
                {k: r.get(k) for k in ("debate_date", "debate_show_as", "debate_id", "debate_section_id", "chamber_name") if k in bd.columns}
                for _, r in (bd.sort_values("debate_date").iterrows() if not bd.empty and "debate_date" in bd.columns else [])
            ],
            "divisions": [
                {k: r.get(k) for k in ("division_id", "vote_id", "division_date", "chamber", "subject", "outcome", "debate_id", "debate_section_id", "debate_show_as") if k in linked_divisions.columns}
                for _, r in linked_divisions.iterrows()
            ],
        })

    root = output_root / f"period={PERIOD}"
    if root.exists():
        shutil.rmtree(root)
    slides_dir = root / "slides"; meta_dir = root / "metadata"; contact_dir = root / "contact_sheets"
    for d in (slides_dir, meta_dir, contact_dir): d.mkdir(parents=True, exist_ok=True)

    slide = slides_dir / "01_inventory_probe.png"
    im = base_slide(); draw = ImageDraw.Draw(im)
    draw.text((540, 130), "THIRD STAGE INVENTORY", font=font(42, True), fill=TEXT, anchor="ma")
    draw.text((540, 195), "DIRECTOR DATA CHECK", font=font(24, True), fill=ACCENT, anchor="ma")
    draw.text((540, 300), f"Validated production batch: {batch.batch_id}", font=font(22, True), fill=TEXT, anchor="ma")
    draw.text((540, 370), f"Current Committee Stage rows: {len(inventory)}", font=font(30, True), fill=ACCENT, anchor="ma")
    y = 465
    for row in inventory[:8]:
        text = f"{row.get('bill_no')}/{row.get('bill_year')}  {row.get('title')}"
        draw.text((90, y), text[:88], font=font(17, True), fill=TEXT, anchor="la")
        y += 68
    draw.text((540, 1220), "Source: validated Oireachtas production batch", font=font(15, True), fill=MUTED, anchor="ma")
    im.save(slide)

    contact = contact_dir / "third_stage_inventory_probe.jpg"
    contact_sheet([("Third Stage inventory", slide)], contact, columns=1)
    payload = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "batch_manifest_status": batch.manifest.get("status"),
        "lineage": lineage,
        "production_third_stage_count": len(inventory),
        "production_current_committee_stage": inventory,
        "table_columns": {name: list(frame.columns) for name, frame in frames.items()},
    }
    caption = root / "caption.txt"
    caption.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest = {
        "project_id": PROJECT_ID,
        "period_key": PERIOD,
        "review_state": "pending_human_review",
        "publication_enabled": False,
        "publishing_allowed": False,
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "source_lineage": lineage,
        "slides": [str(slide)],
        "contact_sheets": {PERIOD: str(contact)},
        "caption": str(caption),
        "render_manifests": {slide.stem: {"renderer": "director_inventory_probe", "source_footer": True}},
        "qa": {
            "expected_slide_count": 1,
            "actual_slide_count": 1,
            "dimensions": [1080, 1350],
            "source_footer_required": True,
            "publication_enabled": False,
            "publishing_allowed": False,
        },
    }
    manifest_path = meta_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "third_stage_inventory_probe.zip")
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest
