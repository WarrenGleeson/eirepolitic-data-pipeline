"""Stage-specific renderers for Third Stage Bill Tracker mockups."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from instagram.factory.render_primitives import ACCENT, BG, MUTED, TEXT, base_slide, font
from instagram.projects.bill_tracker_factory_v1.renderers import (
    W,
    _draw_centered_wrapped,
    _draw_wrapped,
    _fit_wrapped,
    _footer,
    _panel,
    _rule,
    _shared_body_font,
    _title,
)

BOX_W = 456


def _header(draw, bill: dict[str, Any], *, subtitle: str) -> tuple[int, int]:
    title_bottom = _title(draw, bill["formal_title"], top=36, max_width=900, start=34, minimum=23, max_lines=2)
    rule_y = max(116, title_bottom + 18)
    _rule(draw, rule_y)
    stage_y = rule_y + 33
    draw.text((W // 2, stage_y), subtitle, font=font(21, True), fill=ACCENT, anchor="ma")
    return rule_y, stage_y


def render_third_stage_bill(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    _, stage_y = _header(draw, bill, subtitle=f"THIRD STAGE · COMMITTEE STAGE · BILL {bill['bill_number']}")
    meta_y = stage_y + 35
    draw.text((W // 2, meta_y), f"{bill['house']} · {bill.get('committee_date') or bill.get('stage_date')}", font=font(16, True), fill=MUTED, anchor="ma")

    box_top = meta_y + 36; box_h = 230; gap = 20
    boxes = [
        (60, box_top, 516, box_top + box_h),
        (564, box_top, 1020, box_top + box_h),
        (60, box_top + box_h + gap, 516, box_top + 2 * box_h + gap),
        (564, box_top + box_h + gap, 1020, box_top + 2 * box_h + gap),
    ]
    labels = ["WHAT THE BILL DOES", "WHAT HAPPENED AT THIRD STAGE", "KEY AMENDMENT ACTIVITY", "PRACTICAL EFFECT"]
    texts = [bill["what"], bill["happened"], bill["amendments"], bill["effect"]]
    body_font = _shared_body_font(draw, texts, width=BOX_W - 48, height=138, start=21, minimum=15, max_lines=9, gap=3)
    for box, label, text in zip(boxes, labels, texts):
        _panel(draw, box)
        lf, _ = _fit_wrapped(draw, label, width=BOX_W - 48, start=17, minimum=15, max_lines=2, bold=True)
        lend = _draw_wrapped(draw, label, xy=(box[0] + 24, box[1] + 18), f=lf, width=BOX_W - 48, fill=ACCENT, gap=2)
        end = _draw_wrapped(draw, text, xy=(box[0] + 24, max(box[1] + 67, lend + 10)), f=body_font, width=BOX_W - 48, fill=TEXT, gap=3)
        if end > box[3] - 14:
            raise RuntimeError(f"Third Stage body overflow for {label}: {end} > {box[3] - 14}")

    note_top = boxes[2][3] + 24; note_bottom = 1210
    _panel(draw, (60, note_top, 1020, note_bottom), radius=18, outline=ACCENT, width=3, fill=BG)
    draw.text((W // 2, note_top + 25), "WHERE IT IS NOW / WHAT HAPPENS NEXT", font=font(19, True), fill=ACCENT, anchor="ma")
    note_font = _shared_body_font(draw, [bill["where"]], width=850, height=note_bottom - note_top - 86, start=26, minimum=18, max_lines=7, gap=5)
    note_end = _draw_centered_wrapped(draw, bill["where"], cx=W // 2, y=note_top + 74, f=note_font, width=850, fill=TEXT, gap=5)
    if note_end > note_bottom - 18:
        raise RuntimeError(f"Third Stage next-step overflow: {note_end} > {note_bottom - 18}")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer": "bill_tracker_third_stage_bill_v1", "warnings": [], "shared_body_font": body_font.size, "next_step_font": note_font.size, "source_footer": True, "overflow_assertions_passed": True}


def render_amendment_detail(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    _, stage_y = _header(draw, bill, subtitle="THIRD STAGE · AMENDMENT ACTIVITY")
    draw.text((W // 2, stage_y + 36), "Why this Bill needs a second slide", font=font(17, True), fill=MUTED, anchor="ma")
    items = bill.get("amendment_examples") or []
    top = stage_y + 82; gap = 18; box_h = 205
    boxes = [(70, top + i * (box_h + gap), 1010, top + i * (box_h + gap) + box_h) for i in range(len(items))]
    body_texts = [x["detail"] for x in items]
    body_font = _shared_body_font(draw, body_texts, width=720, height=112, start=22, minimum=16, max_lines=6, gap=3)
    for box, item in zip(boxes, items):
        _panel(draw, box)
        draw.text((box[0] + 28, box[1] + 24), str(item["number"]), font=font(28, True), fill=ACCENT, anchor="la")
        draw.text((box[0] + 120, box[1] + 24), str(item["status"]), font=font(20, True), fill=TEXT, anchor="la")
        end = _draw_wrapped(draw, item["detail"], xy=(box[0] + 120, box[1] + 72), f=body_font, width=box[2] - box[0] - 160, fill=TEXT, gap=3)
        if end > box[3] - 18:
            raise RuntimeError(f"Amendment detail overflow: {end} > {box[3] - 18}")
    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer": "bill_tracker_third_stage_amendments_v1", "warnings": [], "shared_body_font": body_font.size, "source_footer": True, "overflow_assertions_passed": True}


def render_compact_third_stage(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    _, stage_y = _header(draw, bill, subtitle=f"THIRD STAGE · CURRENT POSITION · BILL {bill['bill_number']}")
    draw.text((W // 2, stage_y + 36), f"{bill['house']} · checked 10 October 2026", font=font(16, True), fill=MUTED, anchor="ma")

    left = (60, stage_y + 78, 516, 755)
    right = (564, stage_y + 78, 1020, 755)
    bottom = (60, 785, 1020, 1198)
    for box in (left, right, bottom): _panel(draw, box)

    draw.text((left[0] + 24, left[1] + 24), "WHAT THE BILL DOES", font=font(18, True), fill=ACCENT, anchor="la")
    left_font = _shared_body_font(draw, [bill["what"]], width=left[2] - left[0] - 48, height=left[3] - left[1] - 90, start=25, minimum=17, max_lines=12, gap=4)
    lend = _draw_wrapped(draw, bill["what"], xy=(left[0] + 24, left[1] + 72), f=left_font, width=left[2] - left[0] - 48, fill=TEXT, gap=4)
    if lend > left[3] - 18: raise RuntimeError("Compact left box overflow")

    draw.text((right[0] + 24, right[1] + 24), "WHAT WE HAVE AT THIRD STAGE", font=font(18, True), fill=ACCENT, anchor="la")
    right_text = f"{bill['stage_position']}\n\n{bill['available_record']}"
    right_font = _shared_body_font(draw, [right_text], width=right[2] - right[0] - 48, height=right[3] - right[1] - 90, start=22, minimum=15, max_lines=18, gap=4)
    rend = _draw_wrapped(draw, right_text, xy=(right[0] + 24, right[1] + 72), f=right_font, width=right[2] - right[0] - 48, fill=TEXT, gap=4)
    if rend > right[3] - 18: raise RuntimeError("Compact right box overflow")

    draw.text((W // 2, bottom[1] + 28), "WHAT WE SHOULD PRESENT", font=font(20, True), fill=ACCENT, anchor="ma")
    bottom_text = f"{bill['editorial_use']}\n\nNEXT CHECK: {bill['next']}"
    bottom_font = _shared_body_font(draw, [bottom_text], width=850, height=bottom[3] - bottom[1] - 100, start=24, minimum=17, max_lines=12, gap=5)
    bend = _draw_centered_wrapped(draw, bottom_text, cx=W // 2, y=bottom[1] + 82, f=bottom_font, width=850, fill=TEXT, gap=5)
    if bend > bottom[3] - 18: raise RuntimeError("Compact bottom box overflow")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer": "bill_tracker_third_stage_compact_v1", "warnings": [], "left_font": left_font.size, "right_font": right_font.size, "bottom_font": bottom_font.size, "source_footer": True, "overflow_assertions_passed": True}
