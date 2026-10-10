#!/usr/bin/env python3
"""Build three review-only Instagram carousels: TDs, constituencies, parties.

The TD post opens with all TDs at 100% recorded participation, followed by the
highest percentages below 100%, the lowest percentages, the metric explainer,
and methodology. Constituency and party posts remain chart-first four-slide
carousels. Highest/lowest language is descriptive of this metric only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd
from PIL import Image, ImageDraw, ImageFont, ImageOps
from instagram.renderer.constants import FONT_CANDIDATES
from process.director_recorded_voting_participation_prototype_v7 import clean_corner

W, H = 1080, 1350
C = {
    "bg": "#0f2f24",
    "panel": "#173d30",
    "alt": "#214a3b",
    "text": "#f4ead7",
    "muted": "#cbbf9f",
    "gold": "#d8b45f",
}
SESSION = Path("director/sessions/2026-09-27-recorded-voting-participation")
EV = Path(os.getenv("DIRECTOR_VOTE_AUDIT_DIR", str(SESSION / "evidence")))
OUT = SESSION / "split_posts_review"
CEANN_COMHAIRLE_NAME = "Verona Murphy"
CEANN_COMHAIRLE_MEMBER_CODE = "Verona-Murphy.D.2020-02-08"

REPORT = json.loads((EV / "report.json").read_text(encoding="utf-8"))
PERIOD_START = pd.Timestamp(REPORT["resolved_period"]["start"])
PERIOD_END = pd.Timestamp(REPORT["resolved_period"]["end"])
PERIOD = f"{PERIOD_START.day} {PERIOD_START.strftime('%b')}–{PERIOD_END.day} {PERIOD_END.strftime('%b %Y')}"
DIVISIONS = int(REPORT["division_counts"]["included_after_completeness_check"])

CONTEXT = {
    "Mattie McGrath": {
        "marker": "*",
        "short": "Documented health-related absence, 14 Apr 2026",
        "detail": "Documented health-related absence on 14 Apr 2026 following a cardiac procedure.",
        "source": "Tipp Mid West Radio — 14 Apr 2026",
        "url": "https://www.tippmidwestradio.com/2026/04/14/the-dail-is-currently-debating-on-a-motion-of-confidence-in-the-government/",
    },
    "Patrick O'Donovan": {
        "marker": "*",
        "short": "Hospitalised on official business, July 2026",
        "detail": "Hospitalised while on official business in July 2026; later recuperated at home.",
        "source": "RTÉ — 14 Jul 2026",
        "url": "https://www.rte.ie/news/2026/0714/1583374-patrick-odonovan/",
    },
}


def font(size: int, bold: bool = False):
    key = "bold" if bold else "regular"
    for p in FONT_CANDIDATES[key]:
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int) -> str:
    words = text.split()
    lines, current = [], ""
    for word in words:
        probe = word if not current else f"{current} {word}"
        if draw.textbbox((0, 0), probe, font=fnt)[2] <= max_width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def corners(im: Image.Image):
    ref, src = clean_corner()
    size = (round(src.width * W / ref.width), round(src.height * H / ref.height))
    art = src.resize(size, Image.Resampling.LANCZOS)
    for x, y, a in [
        (0, 0, art),
        (W - size[0], 0, ImageOps.mirror(art)),
        (0, H - size[1], ImageOps.flip(art)),
        (W - size[0], H - size[1], ImageOps.mirror(ImageOps.flip(art))),
    ]:
        im.alpha_composite(a, (x, y))


def base(title: str, subtitle: str | None = None):
    im = Image.new("RGBA", (W, H), C["bg"])
    d = ImageDraw.Draw(im)
    corners(im)
    tf = font(43, True)
    while d.textbbox((0, 0), title, font=tf)[2] > 850 and getattr(tf, "size", 31) > 31:
        tf = font(tf.size - 1, True)
    d.text((W // 2, 80), title, font=tf, fill=C["text"], anchor="ma")
    if subtitle:
        sf = font(20)
        d.multiline_text((W // 2, 145), wrap(d, subtitle, sf, 850), font=sf, fill=C["muted"], anchor="ma", align="center", spacing=5)
    d.rectangle((70, 215, 1010, 223), fill=C["gold"])
    return im, d


def save(im: Image.Image, folder: Path, number: int, slug: str):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{number:02d}_{slug}.png"
    im.convert("RGB").save(p)
    return str(p)


def hundred_percent_td_slide(df: pd.DataFrame):
    full = df[df["recorded_participation_pct"] == 100.0].sort_values("member_name", kind="stable").reset_index(drop=True)
    im, d = base("100% Recorded Voting Participation — TDs", f"{PERIOD} · {len(full)} TDs")
    d.rounded_rectangle((72, 265, 1008, 1170), 30, fill=C["panel"], outline=C["alt"], width=2)
    d.rounded_rectangle((335, 300, 745, 430), 28, fill=C["alt"], outline=C["gold"], width=3)
    d.text((540, 338), f"{len(full)} TDs", font=font(34, True), fill=C["text"], anchor="ma")
    d.text((540, 389), "100.0% recorded participation", font=font(18, True), fill=C["gold"], anchor="ma")
    d.text((540, 466), "A recorded Tá, Níl or formal abstention in every eligible division opportunity during the period.", font=font(16), fill=C["muted"], anchor="ma", align="center")
    cols = [full.iloc[:6], full.iloc[6:]]
    xs = [105, 555]
    card_w, card_h, gap = 420, 92, 14
    start_y = 525
    rows = []
    for col_idx, subset in enumerate(cols):
        for row_idx, row in enumerate(subset.itertuples(index=False)):
            x = xs[col_idx]
            y = start_y + row_idx * (card_h + gap)
            d.rounded_rectangle((x, y, x + card_w, y + card_h), 20, fill=C["alt"], outline=C["panel"], width=1)
            d.rounded_rectangle((x + 18, y + 20, x + 104, y + 72), 14, fill=C["gold"])
            d.text((x + 61, y + 46), "100%", font=font(18, True), fill=C["bg"], anchor="mm")
            name = str(row.member_name)
            nf = font(20, True)
            while d.textbbox((0, 0), name, font=nf)[2] > 280 and nf.size > 14:
                nf = font(nf.size - 1, True)
            d.text((x + 125, y + 35), name, font=nf, fill=C["text"], anchor="la")
            d.text((x + 125, y + 66), f"{int(row.recorded_participation_opportunities):,} / {int(row.eligible_division_opportunities):,} eligible opportunities", font=font(11), fill=C["muted"], anchor="la")
            rows.append({"name": name, "recorded": int(row.recorded_participation_opportunities), "eligible": int(row.eligible_division_opportunities), "pct": float(row.recorded_participation_pct)})
    d.text((540, 1210), "100% refers only to this recorded-participation metric.", font=font(13), fill=C["muted"], anchor="ma")
    return im, rows


def explainer(kind: str):
    im, d = base("What This Metric Measures", f"Applied consistently in the {kind.lower()} post")
    d.rounded_rectangle((100, 295, 980, 1040), 30, fill=C["panel"])
    blocks = [
        ("Recorded participation", "An eligible opportunity with a recorded Tá, Níl or formal abstention."),
        ("Eligible divisions", "Membership dates determine whether a division enters a TD’s denominator."),
        ("No recorded vote", "Means only that no qualifying vote or abstention was recorded for that eligible opportunity. It does not establish physical absence."),
        ("Aggregated views", "Party and constituency percentages use summed recorded opportunities divided by summed eligible opportunities — not an average of TD percentages."),
    ]
    y = 345
    for h, t in blocks:
        d.text((145, y), h, font=font(24, True), fill=C["gold"])
        body = wrap(d, t, font(20), 760)
        d.multiline_text((145, y + 38), body, font=font(20), fill=C["text"], spacing=7)
        y += 165
    return im


def selection(df: pd.DataFrame, name_col: str, n: int, highest: bool, exclude_100: bool = False):
    pool = df[df["recorded_participation_pct"] < 100.0].copy() if exclude_100 else df.copy()
    asc = not highest
    ordered = pool.sort_values(["recorded_participation_pct", name_col], ascending=[asc, True], kind="stable").reset_index(drop=True)
    chosen = ordered.head(n).copy()
    boundary = float(chosen.iloc[-1].recorded_participation_pct)
    tied_total = int((pool.recorded_participation_pct == boundary).sum())
    tied_shown = int((chosen.recorded_participation_pct == boundary).sum())
    tie_note = None
    if tied_total > tied_shown:
        tie_note = f"Boundary tie: {tied_total} entries are at {boundary:.1f}%; alphabetical tiebreak used for the {n} shown."
    return chosen, tie_note


def ranking_slide(kind: str, df: pd.DataFrame, name_col: str, n: int, highest: bool, context=False, exclude_100=False):
    direction = "Highest" if highest else "Lowest"
    if highest:
        if kind == "TDs":
            title = "Recorded Voting Participation — TDs"
            subtitle = f"{n} Highest Percentages Below 100% · {PERIOD}" if exclude_100 else f"{n} Highest Recorded-Participation Percentages · {PERIOD}"
        elif kind == "Constituencies":
            title = "Highest Voting Participation — Constituencies"
            subtitle = PERIOD
        elif kind == "Parties":
            title = "Highest Voting Participation — Parties"
            subtitle = PERIOD
        else:
            title = f"{n} Highest Recorded-Participation Percentages"
            subtitle = PERIOD
    else:
        if kind == "Constituencies":
            title = "Lowest Voting Participation — Constituencies"
            subtitle = PERIOD
        elif kind == "Parties":
            title = "Lowest Voting Participation — Parties"
            subtitle = PERIOD
        else:
            title = f"{n} {direction} Recorded-Participation Percentages"
            subtitle = f"{kind} · {PERIOD}"
    im, d = base(title, subtitle)
    chosen, tie_note = selection(df, name_col, n, highest, exclude_100=exclude_100)
    panel_bottom = 1080 if context else 1165
    panel = (58, 260, 1022, panel_bottom)
    d.rounded_rectangle(panel, 28, fill=C["panel"], outline=C["alt"], width=2)
    d.text((86, 285), kind.upper(), font=font(14, True), fill=C["muted"])
    d.text((982, 285), "RATE  ·  RECORDED / ELIGIBLE", font=font(14, True), fill=C["muted"], anchor="ra")
    top, bottom = 320, panel_bottom - 30
    rh = (bottom - top) / len(chosen)
    selected_rows = []
    context_names = []
    for j, row in enumerate(chosen.itertuples(index=False)):
        cy = int(top + (j + 0.5) * rh)
        y0 = int(top + j * rh)
        if j:
            d.line((80, y0, 994, y0), fill=C["alt"], width=1)
        name = str(getattr(row, name_col))
        if "People Before Profit" in name:
            name = "People Before Profit"
        marker = ""
        if context and name in CONTEXT:
            marker = CONTEXT[name]["marker"]
            context_names.append(name)
        display = name + marker
        nf = font(18, True)
        while d.textbbox((0, 0), display, font=nf)[2] > 320 and nf.size > 12:
            nf = font(nf.size - 1, True)
        d.text((86, cy), display, font=nf, fill=C["text"], anchor="lm")
        pct = float(row.recorded_participation_pct)
        bx, bw, bh = 430, 345, 26
        d.rounded_rectangle((bx, cy - bh // 2, bx + bw, cy + bh // 2), 7, fill=C["alt"])
        d.rounded_rectangle((bx, cy - bh // 2, int(bx + bw * pct / 100), cy + bh // 2), 7, fill=C["gold"])
        d.text((982, cy - 4), f"{pct:.1f}%", font=font(19, True), fill=C["text"], anchor="rs")
        d.text((982, cy + 12), f"{int(row.recorded_participation_opportunities):,} / {int(row.eligible_division_opportunities):,}", font=font(12), fill=C["muted"], anchor="ra")
        selected_rows.append({"name": name, "recorded": int(row.recorded_participation_opportunities), "eligible": int(row.eligible_division_opportunities), "pct": pct})
    if context:
        y = 1100
        for name in context_names:
            d.text((90, y), f"* {name} — {CONTEXT[name]['short']}.", font=font(15, True), fill=C["muted"])
            y += 32
        d.text((90, 1212), "Context flags identify documented circumstances only; they are not assigned as the reason for every unrecorded division.", font=font(13), fill=C["gold"])
    elif tie_note:
        d.text((W // 2, 1192), tie_note, font=font(13), fill=C["muted"], anchor="ma")
    return im, selected_rows, tie_note


def methodology(kind: str, n: int):
    im, d = base("Methodology & Limitations", f"{kind} post · {PERIOD}")
    d.rounded_rectangle((80, 265, 1000, 1130), 28, fill=C["panel"])
    if kind == "TDs":
        selection_text = f"Selection: all TDs at 100.0%, then the {n} highest percentages below 100.0%, and the {n} lowest percentages; equal percentages use alphabetical tiebreaks where a boundary tie must be resolved."
    else:
        selection_text = f"Selection: {n} highest and {n} lowest percentages for this metric; equal percentages use alphabetical tiebreaks where a boundary tie must be resolved."
    items = [
        f"Period: {PERIOD} inclusive; {DIVISIONS} production-supported Dáil divisions.",
        "Grain: one eligible TD × division opportunity. Numerator = recorded Tá, Níl or formal abstention; denominator = eligible division opportunities.",
        "Membership dates define eligibility. Party and constituency are attributed using event-date histories.",
        "Party and constituency percentages are calculated from summed numerators and denominators, not average TD percentages.",
        "Identified presiding members are excluded from ordinary eligible opportunities unless that member has a recorded vote, preserving a casting-vote case.",
        "No canonical pairing/statutory-leave field exists in the promoted production batch, so the denominator is not adjusted for those circumstances.",
        selection_text,
        "Recorded voting participation does not by itself measure a TD’s attendance, workload, effectiveness, or overall job performance.",
    ]
    y = 310
    for item in items:
        body = wrap(d, "• " + item, font(17), 820)
        d.multiline_text((125, y), body, font=font(17), fill=C["text"], spacing=5)
        box = d.multiline_textbbox((125, y), body, font=font(17), spacing=5)
        y = box[3] + 23
    if kind == "TDs":
        d.text((125, 1085), "Context sources: Tipp Mid West Radio (14 Apr 2026); RTÉ (14 Jul 2026).", font=font(12), fill=C["muted"])
    return im


def build_post(kind: str, df: pd.DataFrame, name_col: str, n: int):
    folder = OUT / kind.lower().replace(" ", "_")
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("[0-9][0-9]_*.png"):
        old.unlink()
    contact_sheet = folder / "contact_sheet.png"
    if contact_sheet.exists():
        contact_sheet.unlink()
    slides = []
    if kind == "TDs":
        if df["member_name"].astype(str).eq(CEANN_COMHAIRLE_NAME).any() or df["member_code"].astype(str).eq(CEANN_COMHAIRLE_MEMBER_CODE).any():
            raise RuntimeError("Ceann Comhairle still present in TD review data before rendering")
        full_im, full_rows = hundred_percent_td_slide(df)
        slides.append(save(full_im, folder, 1, "100_percent"))
        hi, hi_rows, hi_tie = ranking_slide(kind, df, name_col, n, True, context=False, exclude_100=True)
        slides.append(save(hi, folder, 2, "highest_below_100"))
        lo, lo_rows, lo_tie = ranking_slide(kind, df, name_col, n, False, context=True)
        slides.append(save(lo, folder, 3, "lowest"))
        slides.append(save(explainer(kind), folder, 4, "metric"))
        slides.append(save(methodology(kind, n), folder, 5, "methodology"))
        return {"kind": kind, "n": n, "slide_order": ["100_percent", "highest_below_100", "lowest", "metric", "methodology"], "slides": slides, "hundred_percent": full_rows, "highest_below_100": hi_rows, "lowest": lo_rows, "highest_boundary_tie_note": hi_tie, "lowest_boundary_tie_note": lo_tie}
    hi, hi_rows, hi_tie = ranking_slide(kind, df, name_col, n, True, context=False)
    slides.append(save(hi, folder, 1, "highest"))
    lo, lo_rows, lo_tie = ranking_slide(kind, df, name_col, n, False, context=False)
    slides.append(save(lo, folder, 2, "lowest"))
    slides.append(save(explainer(kind), folder, 3, "metric"))
    slides.append(save(methodology(kind, n), folder, 4, "methodology"))
    return {"kind": kind, "n": n, "slide_order": ["highest", "lowest", "metric", "methodology"], "slides": slides, "highest": hi_rows, "lowest": lo_rows, "highest_boundary_tie_note": hi_tie, "lowest_boundary_tie_note": lo_tie}


def qa(paths):
    issues = []
    for p in paths:
        img = Image.open(p)
        if img.size != (W, H):
            issues.append({"file": p, "issue": f"unexpected dimensions {img.size}"})
    return {"pass": not issues, "issues": issues, "expected_dimensions": [W, H]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    td = pd.read_csv(EV / "td_participation.csv")
    con = pd.read_csv(EV / "constituency_participation.csv")
    party = pd.read_csv(EV / "party_participation.csv")
    td = td[~td["member_name"].astype(str).eq(CEANN_COMHAIRLE_NAME) & ~td["member_code"].astype(str).eq(CEANN_COMHAIRLE_MEMBER_CODE)].copy()
    posts = [build_post("TDs", td, "member_name", 10), build_post("Constituencies", con, "constituency_name", 10), build_post("Parties", party, "party_name", 5)]
    all_paths = [p for post in posts for p in post["slides"]]
    visual_qa = qa(all_paths)
    manifest = {
        "status": "PASS" if visual_qa["pass"] else "FAIL",
        "review_only": True,
        "publication_enabled": False,
        "evidence_source": str(EV),
        "period": REPORT["resolved_period"],
        "division_count": DIVISIONS,
        "td_exclusions": [CEANN_COMHAIRLE_NAME],
        "td_slide_order": ["100_percent", "highest_below_100", "lowest", "metric", "methodology"],
        "other_slide_order": ["highest", "lowest", "metric", "methodology"],
        "selection_rule": "TDs: all 100% entries shown first, then highest values below 100%; all selections use recorded-participation percentage with alphabetical tiebreaks where required. Constituencies/parties retain highest/lowest selection.",
        "interpretation": "Highest/lowest and 100% describe this metric only and are not an overall performance ranking.",
        "required_statement": "Recorded voting participation does not by itself measure a TD’s attendance, workload, effectiveness, or overall job performance.",
        "td_context": CONTEXT,
        "posts": posts,
        "computer_visual_qa": visual_qa,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if visual_qa["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
