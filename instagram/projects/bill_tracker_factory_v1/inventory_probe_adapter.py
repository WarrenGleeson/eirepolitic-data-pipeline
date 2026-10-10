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


def generate(*, project: dict[str, Any], period_spec: str, output_root: Path) -> dict[str, Any]:
    batch = resolve_validated_production_batch()
    names = ["silver_bills", "silver_bill_stages", "silver_bill_sponsors", "silver_bill_debates", "silver_speeches", "silver_divisions", "silver_member_votes"]
    f, lineage = load_csv_tables(batch, names)
    bills, stages = f["silver_bills"], f["silver_bill_stages"]
    current = stages[
        stages["stage_name"].astype(str).str.strip().eq("Committee Stage")
        & stages["stage_outcome"].astype(str).str.strip().str.casefold().eq("current")
    ].copy()
    if "snapshot_date" in current.columns:
        current = current.sort_values(["bill_id", "snapshot_date", "stage_date"]).drop_duplicates("bill_id", keep="last")

    inventory = []
    for _, st in current.iterrows():
        bill_id = str(st["bill_id"])
        b = bills[bills["bill_id"].astype(str).eq(bill_id)].copy()
        if not b.empty and "snapshot_date" in b.columns:
            b = b.sort_values("snapshot_date")
        br = b.iloc[-1] if not b.empty else {}
        bd = f["silver_bill_debates"][f["silver_bill_debates"]["bill_id"].astype(str).eq(bill_id)].copy()
        debate_pairs = {(str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) for _, r in bd.iterrows()}
        debate_ids = {x[0] for x in debate_pairs if x[0]}
        sp = f["silver_speeches"]
        linked_speeches = sp[sp["debate_id"].astype(str).isin(debate_ids)].copy() if debate_ids else sp.iloc[0:0]
        if not linked_speeches.empty and "debate_section_id" in linked_speeches.columns:
            linked_speeches = linked_speeches[linked_speeches.apply(lambda r: (str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) in debate_pairs, axis=1)]
        dv = f["silver_divisions"]
        linked_divisions = dv[dv["debate_id"].astype(str).isin(debate_ids)].copy() if debate_ids else dv.iloc[0:0]
        if not linked_divisions.empty and "debate_section_id" in linked_divisions.columns:
            linked_divisions = linked_divisions[linked_divisions.apply(lambda r: (str(r.get("debate_id") or ""), str(r.get("debate_section_id") or "")) in debate_pairs, axis=1)]
        div_ids = set(linked_divisions["division_id"].astype(str)) if "division_id" in linked_divisions.columns else set()
        mv = f["silver_member_votes"]
        linked_votes = mv[mv["division_id"].astype(str).isin(div_ids)] if div_ids else mv.iloc[0:0]
        ss = f["silver_bill_sponsors"]
        sponsor_count = int(ss[ss["bill_id"].astype(str).eq(bill_id)].shape[0])
        inventory.append({
            "bill_id": bill_id,
            "bill_no": str(br.get("bill_no") or ""),
            "bill_year": str(br.get("bill_year") or ""),
            "title": str(br.get("title") or br.get("short_title") or ""),
            "status": str(br.get("status") or ""),
            "origin_house_name": str(br.get("origin_house_name") or ""),
            "last_event_date": str(br.get("last_event_date") or ""),
            "stage_date": str(st.get("stage_date") or ""),
            "stage_house_name": str(st.get("house_name") or ""),
            "stage_snapshot_date": str(st.get("snapshot_date") or ""),
            "sponsor_rows": sponsor_count,
            "bill_debate_rows": int(len(bd)),
            "linked_speech_rows": int(len(linked_speeches)),
            "linked_division_rows": int(len(linked_divisions)),
            "linked_member_vote_rows": int(len(linked_votes)),
            "division_summaries": [
                {
                    "division_date": str(r.get("division_date") or ""),
                    "subject": str(r.get("subject") or ""),
                    "outcome": str(r.get("outcome") or ""),
                    "debate_show_as": str(r.get("debate_show_as") or ""),
                }
                for _, r in linked_divisions.iterrows()
            ],
        })

    compact = {
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "batch_manifest_status": batch.manifest.get("status"),
        "production_third_stage_count": len(inventory),
        "production_current_committee_stage": inventory,
        "table_row_counts": {k: int(len(v)) for k, v in f.items()},
    }

    root = output_root / f"period={PERIOD}"
    if root.exists(): shutil.rmtree(root)
    slides = root / "slides"; meta = root / "metadata"; contacts = root / "contact_sheets"
    for d in (slides, meta, contacts): d.mkdir(parents=True, exist_ok=True)
    slide = slides / "01_inventory_probe.png"
    im = base_slide(); draw = ImageDraw.Draw(im)
    draw.text((540, 130), "THIRD STAGE INVENTORY", font=font(42, True), fill=TEXT, anchor="ma")
    draw.text((540, 195), "DIRECTOR DATA CHECK", font=font(24, True), fill=ACCENT, anchor="ma")
    draw.text((540, 300), f"Validated batch: {batch.batch_id}", font=font(20, True), fill=TEXT, anchor="ma")
    draw.text((540, 360), f"Current Committee Stage rows: {len(inventory)}", font=font(28, True), fill=ACCENT, anchor="ma")
    y = 445
    for row in inventory[:10]:
        draw.text((70, y), f"{row['bill_no']}/{row['bill_year']}  {row['title']}"[:96], font=font(15, True), fill=TEXT, anchor="la")
        y += 62
    draw.text((540, 1220), "Source: validated Oireachtas production batch", font=font(15, True), fill=MUTED, anchor="ma")
    im.save(slide)
    contact = contacts / "third_stage_inventory_probe.jpg"
    contact_sheet([("Third Stage inventory", slide)], contact, columns=1)
    caption = root / "caption.txt"; caption.write_text(json.dumps(compact, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "project_id": PROJECT_ID, "period_key": PERIOD,
        "review_state": "pending_human_review", "publication_enabled": False, "publishing_allowed": False,
        "source_batch_id": batch.batch_id, "source_pointer": batch.pointer, "source_lineage": lineage,
        "slides": [str(slide)], "contact_sheets": {PERIOD: str(contact)}, "caption": str(caption),
        "render_manifests": {slide.stem: {"renderer": "director_inventory_probe", "source_footer": True}},
        "qa": {"expected_slide_count": 1, "actual_slide_count": 1, "dimensions": [1080, 1350], "source_footer_required": True, "publication_enabled": False, "publishing_allowed": False},
    }
    mp = meta / "manifest.json"; mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    manifest["package"] = deterministic_zip(root, root / "third_stage_inventory_probe.zip")
    mp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return manifest
