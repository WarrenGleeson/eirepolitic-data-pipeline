"""Plain-English enriched Third Stage Bill Tracker renderers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import ImageDraw

from instagram.factory.render_primitives import ACCENT, BG, MUTED, TEXT, base_slide, font, wrap_text_px
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


def _timeline(draw, y: int) -> None:
    stages = ["FIRST", "SECOND", "THIRD", "REPORT", "FINAL"]
    xs = [130, 330, 540, 750, 950]
    draw.line((130, y, 950, y), fill=MUTED, width=3)
    for label, x in zip(stages, xs):
        active = label == "THIRD"
        radius = 18 if active else 13
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=ACCENT if active else BG, outline=ACCENT if active else MUTED, width=3)
        draw.text((x, y+34), label, font=font(14, True), fill=ACCENT if active else MUTED, anchor="ma")


def _bullet_end(draw, bullets: list[str], f, *, x1: int, y1: int, text_w: int, gap: int) -> int:
    y = y1 + 8
    for bullet in bullets:
        lines = wrap_text_px(draw, bullet, f, text_w)
        for line in lines:
            b = draw.textbbox((x1+46, y), line, font=f, anchor="la")
            y = int(b[3] + 4)
        y += gap
    return y


def _bullets(draw, bullets: list[str], *, box: tuple[int,int,int,int], start: int = 22, minimum: int = 13, gap: int = 7) -> int:
    bullets = [str(x).strip() for x in bullets if str(x).strip()]
    if not bullets:
        bullets = ["No additional detail is published in the current source record."]
    x1,y1,x2,y2 = box
    text_w = x2-x1-64
    chosen = None
    for size in range(start, minimum-1, -1):
        candidate = font(size)
        if _bullet_end(draw, bullets, candidate, x1=x1, y1=y1, text_w=text_w, gap=gap) <= y2-5:
            chosen = candidate
            break
    if chosen is None:
        raise RuntimeError(f"Bullets cannot fit safely at minimum size: {bullets!r}")
    y=y1+8
    for bullet in bullets:
        draw.text((x1+14,y+2),"•",font=font(chosen.size+2,True),fill=ACCENT,anchor="la")
        y=_draw_wrapped(draw,bullet,xy=(x1+46,y),f=chosen,width=text_w,fill=TEXT,gap=4)+gap
    if y>y2-5:
        raise RuntimeError(f"bullet overflow: {y}>{y2-5}")
    return chosen.size


def _header(draw, bill: dict[str,Any], strap: str) -> int:
    title_bottom=_title(draw,bill["title"],top=34,max_width=930,start=34,minimum=20,max_lines=3)
    rule_y=max(132,title_bottom+18)
    _rule(draw,rule_y)
    draw.text((W//2,rule_y+34),strap,font=font(20,True),fill=ACCENT,anchor="ma")
    _timeline(draw,rule_y+91)
    return rule_y+145


def render_cover(post_no: int, total_posts: int, bills: list[dict[str, Any]], output: str | Path) -> dict[str, Any]:
    im=base_slide(); draw=ImageDraw.Draw(im)
    draw.text((W//2,145),"BILLS AT THIRD STAGE",font=font(48,True),fill=TEXT,anchor="ma")
    draw.text((W//2,205),f"POST {post_no} OF {total_posts}",font=font(24,True),fill=ACCENT,anchor="ma")
    _rule(draw,248)
    draw.text((W//2,302),"Third Stage is the detailed review stage",font=font(24,True),fill=MUTED,anchor="ma")
    _timeline(draw,372)
    top=465; card_h=150 if len(bills)>=4 else 190; gap=22
    for idx,bill in enumerate(bills,start=1):
        y=top+(idx-1)*(card_h+gap); box=(85,y,995,y+card_h); _panel(draw,box)
        draw.text((115,y+28),str(idx),font=font(28,True),fill=ACCENT,anchor="la")
        f=_shared_body_font(draw,[bill["title"]],width=780,height=card_h-48,start=23,minimum=16,max_lines=4,gap=3)
        end=_draw_wrapped(draw,bill["title"],xy=(170,y+27),f=f,width=780,fill=TEXT,gap=3)
        if end>box[3]-15: raise RuntimeError("cover title overflow")
    _footer(draw,"EirePolitic · Source: Houses of the Oireachtas")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_enriched_cover_v1","source_footer":True,"overflow_assertions_passed":True}


def render_bill_slide(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    """Main enriched Bill slide. bill must contain about_points, stage_points and result."""
    im=base_slide(); draw=ImageDraw.Draw(im)
    y=_header(draw,bill,f"THIRD STAGE · BILL {bill['bill_no']}/{bill['bill_year']}")

    hero=(70,y,1010,y+118); _panel(draw,hero,radius=18,outline=ACCENT,width=3,fill=BG)
    hero_text=str(bill.get("result") or "The Bill is at the detailed review stage.")
    hf=_shared_body_font(draw,[hero_text],width=830,height=78,start=26,minimum=19,max_lines=3,gap=3)
    hend=_draw_centered_wrapped(draw,hero_text,cx=W//2,y=y+28,f=hf,width=830,fill=ACCENT,gap=3)
    if hend>hero[3]-10: raise RuntimeError("hero overflow")
    y=hero[3]+24

    left=(60,y,510,y+430); right=(570,y,1020,y+430)
    for box in (left,right): _panel(draw,box)
    draw.text((84,y+22),"WHAT THIS BILL WOULD DO",font=font(20,True),fill=ACCENT,anchor="la")
    af=_bullets(draw,bill.get("about_points") or [],box=(left[0]+6,left[1]+66,left[2]-6,left[3]-14),start=22,minimum=13)

    draw.text((594,y+22),"WHAT HAS HAPPENED AT THIRD STAGE",font=font(19,True),fill=ACCENT,anchor="la")
    sf=_bullets(draw,bill.get("stage_points") or [],box=(right[0]+6,right[1]+66,right[2]-6,right[3]-14),start=20,minimum=13)

    bottom=(60,y+455,1020,1192); _panel(draw,bottom,radius=18,outline=ACCENT,width=3,fill=BG)
    draw.text((W//2,bottom[1]+28),"WHAT THIS MEANS",font=font(19,True),fill=ACCENT,anchor="ma")
    simple=str(bill.get("simple_takeaway") or bill.get("result") or "The Bill is still being reviewed in detail.")
    tf=_shared_body_font(draw,[simple],width=840,height=125,start=26,minimum=19,max_lines=5,gap=5)
    tend=_draw_centered_wrapped(draw,simple,cx=W//2,y=bottom[1]+82,f=tf,width=840,fill=TEXT,gap=5)

    next_label="WHAT HAPPENS NEXT"
    draw.text((W//2,tend+38),next_label,font=font(17,True),fill=MUTED,anchor="ma")
    next_text=str(bill.get("next_text") or "When the detailed review is complete, the Bill would normally move to Report Stage for another review before the final stage in that House.")
    nf=_shared_body_font(draw,[next_text],width=820,height=118,start=20,minimum=16,max_lines=5,gap=4)
    nend=_draw_centered_wrapped(draw,next_text,cx=W//2,y=tend+78,f=nf,width=820,fill=TEXT,gap=4)
    if nend>bottom[3]-18: raise RuntimeError("bottom overflow")

    _footer(draw,f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_no']}/{bill['bill_year']}")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_enriched_bill_v1","about_font":af,"stage_font":sf,"source_footer":True,"overflow_assertions_passed":True}


def _safe_change_text(change: dict[str,Any]) -> str:
    plain=str(change.get("plain") or "").strip()
    if plain: return plain
    status=str(change.get("status") or "").upper()
    mapping={
        "ACCEPTED":"The official debate record shows at least one proposed wording change was accepted.",
        "REJECTED":"The official debate record shows at least one proposed wording change was rejected.",
        "WITHDRAWN":"The official debate record shows at least one proposed wording change was withdrawn after discussion.",
        "COULD NOT PROCEED":"The official debate record shows at least one proposed wording change could not proceed.",
    }
    return mapping.get(status,"The official debate record contains a decision on a proposed wording change.")


def render_changes_slide(bill: dict[str,Any], output: str | Path) -> dict[str,Any]:
    """Supplementary slide only when verified change/version/division evidence exists."""
    im=base_slide(); draw=ImageDraw.Draw(im)
    y=_header(draw,bill,"THIRD STAGE · CHANGES AND DECISIONS")
    draw.text((W//2,y+12),"What the published record adds",font=font(18,True),fill=MUTED,anchor="ma")
    y+=55

    cards=[]
    for ch in bill.get("change_outcomes") or []:
        cards.append((str(ch.get("status") or "DECISION").upper(),_safe_change_text(ch)))
        if len(cards)>=3: break

    versions=bill.get("amended_versions") or []
    docs=bill.get("amendment_documents") or []
    if versions and len(cards)<3:
        label=str(versions[0].get("label") or "updated Bill").strip()
        cards.append(("UPDATED BILL PUBLISHED",f"An updated version was published after the detailed review: {label}."))
    if docs and len(cards)<3:
        label=str(docs[0].get("label") or "proposed changes document").strip()
        cards.append(("PROPOSED CHANGES PUBLISHED",f"The official record includes a document setting out proposed wording changes: {label}."))
    if not cards:
        cards.append(("PUBLISHED RECORD","The official record contains additional Third Stage material for this Bill."))

    card_h=190; gap=18
    shared=_shared_body_font(draw,[c[1] for c in cards],width=760,height=95,start=21,minimum=16,max_lines=5,gap=3)
    for idx,(status,body) in enumerate(cards):
        top=y+idx*(card_h+gap); box=(70,top,1010,top+card_h); _panel(draw,box)
        draw.text((100,top+28),status,font=font(19,True),fill=ACCENT,anchor="la")
        end=_draw_wrapped(draw,body,xy=(100,top+72),f=shared,width=820,fill=TEXT,gap=3)
        if end>box[3]-14: raise RuntimeError("change card overflow")

    divs=bill.get("divisions") or []
    safe_div=None
    for d in divs:
        if str(d.get("plain") or "").strip() or str(d.get("subject") or "").strip():
            safe_div=d; break
    top=y+len(cards)*(card_h+gap)+8
    if safe_div and top<1050:
        box=(70,top,1010,1188); _panel(draw,box,radius=18,outline=ACCENT,width=3,fill=BG)
        draw.text((100,top+28),"RECORDED VOTE",font=font(18,True),fill=MUTED,anchor="la")
        if str(safe_div.get("plain") or "").strip():
            body=str(safe_div["plain"]).strip()
        else:
            subject=str(safe_div.get("subject") or "").strip()
            outcome=str(safe_div.get("outcome") or "").strip()
            tally=str(safe_div.get("tally") or "").strip()
            body=f"Vote on: {subject}." + (f" Outcome: {outcome}." if outcome else "") + (f" Tally: {tally}." if tally else "") + " This is a vote on that specific proposal, not automatically a vote on the Bill as a whole."
        vf=_shared_body_font(draw,[body],width=820,height=100,start=20,minimum=16,max_lines=5,gap=4)
        vend=_draw_wrapped(draw,body,xy=(100,top+70),f=vf,width=820,fill=TEXT,gap=4)
        if vend>box[3]-14: raise RuntimeError("division card overflow")

    _footer(draw,f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_no']}/{bill['bill_year']}")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_enriched_changes_v1","change_cards":len(cards),"division_shown":bool(safe_div),"source_footer":True,"overflow_assertions_passed":True}


def render_explainer(post_no: int, total_posts: int, output: str | Path) -> dict[str, Any]:
    im=base_slide(); draw=ImageDraw.Draw(im)
    draw.text((W//2,105),"WHAT DOES THIRD STAGE MEAN?",font=font(42,True),fill=TEXT,anchor="ma")
    draw.text((W//2,165),f"POST {post_no} OF {total_posts} · QUICK GUIDE",font=font(20,True),fill=ACCENT,anchor="ma")
    _rule(draw,205); _timeline(draw,275)
    steps=[
        ("1","DETAILED REVIEW","Lawmakers go through the Bill section by section instead of only debating the general idea."),
        ("2","PROPOSED CHANGES","They can suggest changes to the actual wording of the Bill."),
        ("3","DECISIONS","Proposed changes can be accepted, rejected, withdrawn or ruled out."),
        ("4","UPDATED BILL","Any accepted changes become part of the version that moves forward."),
        ("5","NEXT STAGE","The Bill normally moves to Report Stage for another review before the final stage in that House."),
    ]
    y=365; card_h=140; gap=18
    bodyf=_shared_body_font(draw,[s[2] for s in steps],width=700,height=72,start=20,minimum=16,max_lines=4,gap=3)
    for num,head,body in steps:
        box=(70,y,1010,y+card_h); _panel(draw,box)
        draw.text((100,y+34),num,font=font(28,True),fill=ACCENT,anchor="la")
        draw.text((165,y+28),head,font=font(20,True),fill=ACCENT,anchor="la")
        end=_draw_wrapped(draw,body,xy=(165,y+67),f=bodyf,width=760,fill=TEXT,gap=3)
        if end>box[3]-12: raise RuntimeError("explainer overflow")
        y+=card_h+gap
    _footer(draw,"EirePolitic · Source: Houses of the Oireachtas")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_enriched_explainer_v1","body_font":bodyf.size,"source_footer":True,"overflow_assertions_passed":True}
