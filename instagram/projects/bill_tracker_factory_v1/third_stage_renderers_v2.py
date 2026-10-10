"""Audience-facing Third Stage Bill Tracker V2 renderers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from instagram.factory.render_primitives import ACCENT, BG, MUTED, TEXT, base_slide, font
from instagram.projects.bill_tracker_factory_v1.renderers import (
    W,
    _draw_centered_wrapped,
    _draw_wrapped,
    _footer,
    _panel,
    _rule,
    _shared_body_font,
    _title,
)


def _draw_bullets(draw, bullets: list[str], *, box: tuple[int,int,int,int], start_size: int = 23, minimum: int = 17, gap: int = 10) -> int:
    x1, y1, x2, y2 = box
    text_w = x2 - x1 - 68
    available_h = y2 - y1 - 38 - max(0, len(bullets) - 1) * gap
    combined = " ".join(bullets)
    f = _shared_body_font(draw, [combined], width=text_w, height=available_h, start=start_size, minimum=minimum, max_lines=20, gap=4)
    y = y1 + 12
    for bullet in bullets:
        draw.text((x1 + 18, y + 2), "•", font=font(f.size + 2, True), fill=ACCENT, anchor="la")
        y = _draw_wrapped(draw, bullet, xy=(x1 + 50, y), f=f, width=text_w, fill=TEXT, gap=4)
        y += gap
    if y > y2 - 8:
        raise RuntimeError(f"bullet overflow: {y} > {y2 - 8}")
    return f.size


def _hero(draw, text: str, *, y: int) -> int:
    box = (70, y, 1010, y + 112)
    _panel(draw, box, radius=18, outline=ACCENT, width=3, fill=BG)
    f = _shared_body_font(draw, [text], width=840, height=76, start=27, minimum=20, max_lines=3, gap=3)
    end = _draw_centered_wrapped(draw, text, cx=W // 2, y=y + 28, f=f, width=840, fill=ACCENT, gap=3)
    if end > box[3] - 10:
        raise RuntimeError("hero overflow")
    return box[3]


def _timeline(draw, *, active: str, y: int) -> None:
    stages = ["FIRST", "SECOND", "THIRD", "REPORT", "FINAL"]
    xs = [130, 330, 540, 750, 950]
    draw.line((130, y, 950, y), fill=MUTED, width=3)
    for label, x in zip(stages, xs):
        radius = 18 if label == active else 13
        fill = ACCENT if label == active else BG
        outline = ACCENT if label == active else MUTED
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=fill, outline=outline, width=3)
        draw.text((x, y+34), label, font=font(14, True), fill=ACCENT if label == active else MUTED, anchor="ma")


def _header(draw, bill: dict[str, Any], *, strap: str) -> int:
    title_bottom = _title(draw, bill["formal_title"], top=34, max_width=930, start=34, minimum=22, max_lines=2)
    rule_y = max(116, title_bottom + 18)
    _rule(draw, rule_y)
    draw.text((W // 2, rule_y + 34), strap, font=font(20, True), fill=ACCENT, anchor="ma")
    _timeline(draw, active="THIRD", y=rule_y + 91)
    return rule_y + 138


def render_complex_summary(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    y = _header(draw, bill, strap=f"THIRD STAGE · DETAILED REVIEW · BILL {bill['bill_number']}")
    y = _hero(draw, bill["hero"], y=y + 8) + 22

    left = (60, y, 510, y + 395)
    right = (570, y, 1020, y + 395)
    for box in (left, right): _panel(draw, box)
    draw.text((left[0]+24, left[1]+22), "WHAT THE BILL DOES", font=font(20, True), fill=ACCENT, anchor="la")
    draw.text((right[0]+24, right[1]+22), "WHAT HAPPENED AT THIRD STAGE", font=font(20, True), fill=ACCENT, anchor="la")
    lf = _draw_bullets(draw, bill["what_bullets"], box=(left[0]+6, left[1]+66, left[2]-6, left[3]-10), start_size=22, minimum=16)
    rf = _draw_bullets(draw, bill["third_stage_bullets"], box=(right[0]+6, right[1]+66, right[2]-6, right[3]-10), start_size=22, minimum=16)

    result = (60, y + 417, 1020, 1188)
    _panel(draw, result, radius=18, outline=ACCENT, width=3, fill=BG)
    draw.text((90, result[1]+25), "WHAT CAME OUT OF THIRD STAGE", font=font(19, True), fill=ACCENT, anchor="la")
    draw.text((90, result[1]+74), bill["result"].upper(), font=font(30, True), fill=TEXT, anchor="la")
    draw.text((90, result[1]+133), "WHAT HAPPENS NEXT", font=font(17, True), fill=MUTED, anchor="la")
    draw.text((310, result[1]+133), bill["next_stage"], font=font(19, True), fill=ACCENT, anchor="la")
    nf = _shared_body_font(draw, [bill["next_text"]], width=780, height=70, start=21, minimum=17, max_lines=3, gap=4)
    next_end = _draw_wrapped(draw, bill["next_text"], xy=(90, result[1]+171), f=nf, width=780, fill=TEXT, gap=4)
    draw.text((90, max(result[1]+228, next_end+18)), "WHY THIS MATTERS", font=font(17, True), fill=MUTED, anchor="la")
    why_y = max(result[1]+268, next_end+58)
    wf = _shared_body_font(draw, [bill["why_stage"]], width=850, height=result[3]-why_y-22, start=20, minimum=16, max_lines=5, gap=4)
    why_end = _draw_wrapped(draw, bill["why_stage"], xy=(90, why_y), f=wf, width=850, fill=TEXT, gap=4)
    if why_end > result[3]-18:
        raise RuntimeError("why-stage overflow")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer":"third_stage_v2_complex_summary","left_font":lf,"right_font":rf,"why_font":wf.size,"source_footer":True,"overflow_assertions_passed":True}


def render_amendment_story(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    y = _header(draw, bill, strap="THIRD STAGE · WHAT CHANGED")
    draw.text((W // 2, y + 12), "Examples of changes TDs proposed during the detailed review", font=font(18, True), fill=MUTED, anchor="ma")
    y += 55

    cards = bill["amendment_examples"]
    card_h = 185
    detail_x = 390
    shared = _shared_body_font(draw, [c["detail"] for c in cards], width=560, height=95, start=20, minimum=16, max_lines=5, gap=3)
    for i, c in enumerate(cards):
        top = y + i * (card_h + 16)
        box = (65, top, 1015, top + card_h)
        _panel(draw, box)
        draw.text((92, top+28), f"PROPOSED CHANGE {c['number']}", font=font(17, True), fill=MUTED, anchor="la")
        draw.text((detail_x, top+28), c["status"], font=font(20, True), fill=ACCENT, anchor="la")
        draw.text((92, top+70), c["title"], font=font(21, True), fill=TEXT, anchor="la")
        end = _draw_wrapped(draw, c["detail"], xy=(detail_x, top+67), f=shared, width=560, fill=TEXT, gap=3)
        if end > box[3]-15: raise RuntimeError("proposed-change card overflow")

    div = bill["division"]
    top = y + len(cards)*(card_h+16) + 4
    box = (65, top, 1015, 1187)
    _panel(draw, box, radius=18, outline=ACCENT, width=3, fill=BG)
    draw.text((92, top+28), "VOTE ON ONE PROPOSED CHANGE", font=font(17, True), fill=MUTED, anchor="la")
    draw.text((92, top+72), div["status"], font=font(25, True), fill=ACCENT, anchor="la")
    draw.text((735, top+72), div["tally"], font=font(28, True), fill=TEXT, anchor="ma")
    df = _shared_body_font(draw, [div["detail"]], width=850, height=82, start=20, minimum=17, max_lines=4, gap=3)
    div_end = _draw_wrapped(draw, div["detail"], xy=(92, top+122), f=df, width=850, fill=TEXT, gap=3)
    if div_end > box[3]-15:
        raise RuntimeError("division overflow")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer":"third_stage_v2_amendment_story","shared_font":shared.size,"source_footer":True,"overflow_assertions_passed":True}


def render_status_case(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    y = _header(draw, bill, strap=f"THIRD STAGE · WHERE IT IS NOW · BILL {bill['bill_number']}")
    y = _hero(draw, bill["hero"], y=y + 8) + 24

    what = (60, y, 510, y + 330)
    status = (570, y, 1020, y + 330)
    for box in (what, status): _panel(draw, box)
    draw.text((84, y+22), "WHAT THE BILL DOES", font=font(20, True), fill=ACCENT, anchor="la")
    draw.text((594, y+22), "WHAT HAS HAPPENED SO FAR", font=font(20, True), fill=ACCENT, anchor="la")
    wf = _draw_bullets(draw, bill["what_bullets"], box=(what[0]+6, what[1]+66, what[2]-6, what[3]-10), start_size=20, minimum=15)
    sf = _draw_bullets(draw, bill["status_bullets"], box=(status[0]+6, status[1]+66, status[2]-6, status[3]-10), start_size=19, minimum=14)

    watch = (60, y+352, 1020, y+582)
    _panel(draw, watch)
    draw.text((84, watch[1]+22), "WHAT TO LOOK FOR NEXT", font=font(20, True), fill=ACCENT, anchor="la")
    watch_font = _draw_bullets(draw, bill["watch_bullets"], box=(watch[0]+6, watch[1]+62, watch[2]-6, watch[3]-10), start_size=19, minimum=15, gap=7)

    take = (60, y+604, 1020, 1190)
    _panel(draw, take, radius=18, outline=ACCENT, width=3, fill=BG)
    draw.text((W//2, take[1]+26), "IN SIMPLE TERMS", font=font(18, True), fill=ACCENT, anchor="ma")
    tf = _shared_body_font(draw, [bill["takeaway"]], width=850, height=125, start=27, minimum=20, max_lines=5, gap=5)
    end = _draw_centered_wrapped(draw, bill["takeaway"], cx=W//2, y=take[1]+80, f=tf, width=850, fill=TEXT, gap=5)
    if end > take[3]-15: raise RuntimeError("takeaway overflow")

    _footer(draw, f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_number']}")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer":"third_stage_v2_status_case","what_font":wf,"status_font":sf,"watch_font":watch_font,"source_footer":True,"overflow_assertions_passed":True}
