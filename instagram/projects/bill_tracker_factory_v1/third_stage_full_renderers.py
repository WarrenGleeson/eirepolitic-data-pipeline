"""Plain-English full-series renderers for Third Stage Bill Tracker review."""
from __future__ import annotations

import re
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


def _timeline(draw, y: int) -> None:
    stages = ["FIRST", "SECOND", "THIRD", "REPORT", "FINAL"]
    xs = [130, 330, 540, 750, 950]
    draw.line((130, y, 950, y), fill=MUTED, width=3)
    for label, x in zip(stages, xs):
        active = label == "THIRD"
        radius = 18 if active else 13
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=ACCENT if active else BG, outline=ACCENT if active else MUTED, width=3)
        draw.text((x, y+34), label, font=font(14, True), fill=ACCENT if active else MUTED, anchor="ma")


def _clean_subject(title: str) -> str:
    t = re.sub(r"\s+Bill\s+\d{4}$", "", title).strip()
    t = re.sub(r"\s*\((?:Amendment|Miscellaneous Provisions)(?:\s*\([^)]*\))?\)\s*", " ", t, flags=re.I)
    t = re.sub(r"\s*\(No\.\s*\d+\)\s*", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t


def plain_about(title: str) -> str:
    low = title.casefold()
    subject = _clean_subject(title)
    special = [
        ("online age verification", "Sets rules for checking age online to help protect children."),
        ("strategic lawsuits against public participation", "Aims to protect people and groups from lawsuits used to discourage them from speaking out on public issues."),
        ("lethal autonomous weapons", "Would ban certain weapons that can select and attack targets without direct human control."),
        ("seller’s legal pack", "Would require key legal information about a home to be prepared earlier when it is being sold."),
        ("seller's legal pack", "Would require key legal information about a home to be prepared earlier when it is being sold."),
        ("social welfare, civil registration and charities", "Changes some social welfare rules, official civil records and charities law."),
        ("tobacco products and nicotine", "Changes rules on tobacco and nicotine products, including newer nicotine products."),
        ("broadcasting", "Changes some rules for broadcasting, public-service media and how parts of the media system are overseen."),
        ("pregnancy loss", "Deals with legal and workplace issues connected with pregnancy loss."),
        ("assisted human reproduction", "Deals with rules around assisted human reproduction and fertility treatment."),
        ("defective dwellings", "Deals with homes affected by serious building defects and how those problems are addressed."),
        ("flood insurance", "Deals with access to flood insurance and related insurance rules."),
        ("domestic violence", "Changes parts of the law dealing with domestic violence and legal protections for victims."),
        ("minimum wage", "Changes minimum-wage rules, including how they apply to younger workers."),
        ("living wage", "Deals with rules around introducing or recognising a living wage."),
        ("sex for rent", "Targets situations where housing is offered or advertised in exchange for sex."),
        ("cannabis regulation", "Would create a legal framework for regulating cannabis."),
        ("voting at 16", "Would lower the voting age to 16 for the elections covered by the Bill."),
        ("period products", "Would provide period products free of charge in the settings covered by the Bill."),
        ("anti-evictions", "Would change housing law with the aim of giving tenants stronger protection from eviction."),
        ("homeless families", "Deals with how housing law and public services treat families experiencing homelessness."),
        ("animal health and welfare (dogs)", "Changes rules aimed at protecting the health and welfare of dogs."),
        ("control of dogs", "Changes rules on dog control and responsible ownership."),
        ("pay transparency", "Would require more openness about pay and pay differences."),
        ("carbon footprint labelling", "Would create rules for showing the carbon footprint of certain products or services."),
        ("traveller culture and history", "Would require greater inclusion of Traveller culture and history in education."),
        ("objective sex education", "Deals with how sex education is provided in schools."),
        ("future generations", "Would create a body or duties focused on the long-term impact of government decisions on future generations."),
    ]
    for needle, sentence in special:
        if needle in low:
            return sentence
    if "amendment of the constitution" in low:
        return f"Would change the Constitution in relation to {subject.split('Constitution', 1)[-1].strip(' ()-').lower() or 'the issue named in the Bill'}."
    if title.startswith("Prohibition of "):
        return f"Would ban or restrict {subject[len('Prohibition of '):].lower()}."
    if title.startswith("Protection of "):
        return f"Would create legal protections connected with {subject[len('Protection of '):].lower()}."
    if title.startswith("Free Provision of "):
        return f"Would require free provision of {subject[len('Free Provision of '):].lower()}."
    if "(Amendment)" in title or "(Amendment)" in title.replace("No. 2", ""):
        return f"Changes existing law dealing with {subject.lower()}."
    return f"Deals with {subject.lower()}."


def render_cover(post_no: int, total_posts: int, bills: list[dict[str, Any]], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    draw.text((W//2, 145), "BILLS AT THIRD STAGE", font=font(48, True), fill=TEXT, anchor="ma")
    draw.text((W//2, 205), f"POST {post_no} OF {total_posts}", font=font(24, True), fill=ACCENT, anchor="ma")
    _rule(draw, 248)
    draw.text((W//2, 302), "Third Stage is the detailed review stage", font=font(24, True), fill=MUTED, anchor="ma")
    _timeline(draw, 372)

    top = 465
    card_h = 150 if len(bills) >= 4 else 190
    gap = 22
    for idx, bill in enumerate(bills, start=1):
        y = top + (idx-1)*(card_h+gap)
        box = (85, y, 995, y+card_h)
        _panel(draw, box)
        draw.text((115, y+28), f"{idx}", font=font(28, True), fill=ACCENT, anchor="la")
        f = _shared_body_font(draw, [bill["title"]], width=780, height=card_h-48, start=23, minimum=17, max_lines=4, gap=3)
        end = _draw_wrapped(draw, bill["title"], xy=(170, y+27), f=f, width=780, fill=TEXT, gap=3)
        if end > box[3]-15:
            raise RuntimeError("cover title overflow")

    _footer(draw, "EirePolitic · Source: Houses of the Oireachtas")
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True); im.save(output)
    return {"renderer":"third_stage_full_cover_v1","source_footer":True,"overflow_assertions_passed":True}


def render_bill_slide(bill: dict[str, Any], output: str | Path) -> dict[str, Any]:
    im = base_slide(); draw = ImageDraw.Draw(im)
    title_bottom = _title(draw, bill["title"], top=34, max_width=930, start=34, minimum=21, max_lines=3)
    rule_y = max(132, title_bottom+18); _rule(draw, rule_y)
    draw.text((W//2, rule_y+34), f"THIRD STAGE · BILL {bill['bill_no']}/{bill['bill_year']}", font=font(20, True), fill=ACCENT, anchor="ma")
    _timeline(draw, rule_y+91)
    y = rule_y+145

    hero = (70, y, 1010, y+112)
    _panel(draw, hero, radius=18, outline=ACCENT, width=3, fill=BG)
    draw.text((W//2, y+31), "THE BILL IS NOW AT THE DETAILED REVIEW STAGE", font=font(24, True), fill=ACCENT, anchor="ma")
    y = hero[3]+24

    left=(60,y,510,y+365); right=(570,y,1020,y+365)
    for box in (left,right): _panel(draw,box)
    draw.text((84,y+22),"WHAT THIS BILL IS ABOUT",font=font(20,True),fill=ACCENT,anchor="la")
    about = plain_about(bill["title"])
    af = _shared_body_font(draw,[about],width=370,height=245,start=25,minimum=18,max_lines=9,gap=5)
    aend = _draw_wrapped(draw,about,xy=(84,y+75),f=af,width=370,fill=TEXT,gap=5)
    if aend > left[3]-18: raise RuntimeError("about overflow")

    draw.text((594,y+22),"WHAT THIRD STAGE MEANS HERE",font=font(20,True),fill=ACCENT,anchor="la")
    stage_lines = [
        "Lawmakers can go through the Bill in detail and suggest changes to its wording.",
        f"The official record currently shows Third Stage from {bill.get('live_stage_date') or 'the latest recorded date'}.",
    ]
    if bill.get("complexity") == "complex":
        stage_lines.append("This Bill has a larger parliamentary record, so any important changes or votes will be checked separately before final publication.")
    else:
        stage_lines.append("The next useful update is whether any proposed wording changes are accepted or rejected.")
    sf = _shared_body_font(draw,[" ".join(stage_lines)],width=370,height=245,start=21,minimum=15,max_lines=13,gap=4)
    sy=y+75
    for line in stage_lines:
        draw.text((594,sy+1),"•",font=font(sf.size+2,True),fill=ACCENT,anchor="la")
        sy=_draw_wrapped(draw,line,xy=(625,sy),f=sf,width=330,fill=TEXT,gap=4)+10
    if sy > right[3]-10: raise RuntimeError("stage box overflow")

    bottom=(60,y+390,1020,1190)
    _panel(draw,bottom,radius=18,outline=ACCENT,width=3,fill=BG)
    draw.text((W//2,bottom[1]+30),"IN SIMPLE TERMS",font=font(19,True),fill=ACCENT,anchor="ma")
    takeaway = "The Bill has passed the broad debate stage. Now the focus is on the exact wording and whether it should be changed before moving on."
    tf=_shared_body_font(draw,[takeaway],width=850,height=150,start=27,minimum=20,max_lines=5,gap=5)
    tend=_draw_centered_wrapped(draw,takeaway,cx=W//2,y=bottom[1]+90,f=tf,width=850,fill=TEXT,gap=5)
    draw.text((W//2,tend+38),"WHAT HAPPENS NEXT",font=font(17,True),fill=MUTED,anchor="ma")
    next_text="Once this detailed review is finished, the Bill would normally move to Report Stage for another round of review before the final stage in that House."
    nf=_shared_body_font(draw,[next_text],width=820,height=120,start=20,minimum=16,max_lines=5,gap=4)
    nend=_draw_centered_wrapped(draw,next_text,cx=W//2,y=tend+80,f=nf,width=820,fill=TEXT,gap=4)
    if nend > bottom[3]-18: raise RuntimeError("bottom overflow")

    _footer(draw,f"EirePolitic · Source: Houses of the Oireachtas · Bill {bill['bill_no']}/{bill['bill_year']}")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_full_bill_v1","about_font":af.size,"stage_font":sf.size,"source_footer":True,"overflow_assertions_passed":True}


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
        if end > box[3]-12: raise RuntimeError("explainer overflow")
        y += card_h+gap
    _footer(draw,"EirePolitic · Source: Houses of the Oireachtas")
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); im.save(output)
    return {"renderer":"third_stage_full_explainer_v1","body_font":bodyf.size,"source_footer":True,"overflow_assertions_passed":True}
