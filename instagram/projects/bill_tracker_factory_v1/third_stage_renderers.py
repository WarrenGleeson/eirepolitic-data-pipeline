"""Stage-specific renderer for the Third Stage Bill Tracker prototype."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from instagram.factory.render_primitives import ACCENT, BG, MUTED, TEXT, base_slide, font
from instagram.projects.bill_tracker_factory_v1.renderers import (
    W,
    _draw_wrapped,
    _fit_wrapped,
    _footer,
    _panel,
    _rule,
    _shared_body_font,
    _title,
    _wrap,
)

BOX_W = 456


def _draw_centered(draw, text: str, *, cx: int, y: int, f, width: int, fill, gap: int = 4) -> int:
    lines = _wrap(draw, text, f, width)
    line_h = draw.textbbox((0, 0), "Ag", font=f)[3]
    for line in lines:
        draw.text((cx, y), line, font=f, fill=fill, anchor="ma")
        y += line_h + gap
    return y


def render_third_stage_bill(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    title_bottom = _title(draw, bill["formal_title"], top=36, max_width=900, start=34, minimum=24, max_lines=2)
    rule_y = max(116, title_bottom + 18); _rule(draw, rule_y)
    stage_y = rule_y + 33
    draw.text((W // 2, stage_y), f"THIRD STAGE · COMMITTEE STAGE · BILL {bill['bill_number']}", font=font(21, True), fill=ACCENT, anchor="ma")
    meta_y = stage_y + 35
    draw.text((W // 2, meta_y), f"{bill['house']} · {bill['committee_date']}", font=font(16, True), fill=MUTED, anchor="ma")

    box_top = meta_y + 36; box_h = 230; gap = 20
    boxes = [
        (60, box_top, 516, box_top + box_h),
        (564, box_top, 1020, box_top + box_h),
        (60, box_top + box_h + gap, 516, box_top + 2 * box_h + gap),
        (564, box_top + box_h + gap, 1020, box_top + 2 * box_h + gap),
    ]
    labels = ["WHAT THE BILL DOES", "WHAT HAPPENED AT THIRD STAGE", "KEY AMENDMENT ACTIVITY", "PRACTICAL EFFECT"]
    texts = [bill["what"], bill["happened"], bill["amendments"], bill["effect"]]
    body_font = _shared_body_font(draw, texts, width=BOX_W - 48, height=150, start=21, minimum=15, max_lines=9, gap=3)
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
    note_end = _draw_centered(draw, bill["where"], cx=W // 2, y=note_top + 74, f=note_font, width=850, fill=TEXT, gap=5)
    if note_end > note_bottom - 18:
        raise RuntimeError(f"Third Stage next-step overflow: {note_end} > {note_bottom - 18}")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {
        "renderer": "bill_tracker_third_stage_bill_v1",
        "warnings": [],
        "shared_body_font": body_font.size,
        "next_step_font": note_font.size,
        "source_footer": True,
        "overflow_assertions_passed": True,
    }
