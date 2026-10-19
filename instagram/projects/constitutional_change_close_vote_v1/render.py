from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG = "#0f2f24"
TEXT = "#f4ead7"
ACCENT = "#d8b45f"
MUTED = "#c8bda8"
GRID = "#315448"
YES = "#d8b45f"
NO = "#88a99a"
LEFT = 104
RIGHT = 976

SLIDES = [
    {
        "title": "A Bill to require formal planning for constitutional change lost by 10 votes",
        "kicker": "Dáil Éireann · 8 July 2026",
        "kind": "cover",
    },
    {
        "title": "What was actually being voted on?",
        "kicker": "Planning for Constitutional Change Bill 2026 · Second Stage",
        "body": [
            "The Dáil was deciding whether the Bill should proceed beyond Second Stage.",
            "It would have required the Government to begin a formal planning process for possible constitutional change and Irish reunification.",
            "This was not a direct vote on Irish unity.",
        ],
        "kind": "body",
    },
    {
        "title": "What did the Bill propose?",
        "kicker": "A defined planning process",
        "steps": [
            "Government Green Paper",
            "Public and political consultation",
            "All-island Citizens' Assembly",
            "Reporting to the Oireachtas",
        ],
        "kind": "flow",
    },
    {
        "title": "Why did supporters back it?",
        "kicker": "The case for beginning preparation now",
        "body": [
            "Sinn Féin argued that constitutional change should be prepared for before a referendum is on the immediate horizon.",
            "The case was that questions around public services, the economy, governance and constitutional arrangements should be examined openly and in advance.",
        ],
        "kind": "body",
    },
    {
        "title": "Why did Government oppose it?",
        "kicker": "The objection centred on mechanism and timetable",
        "body": [
            "Taoiseach Micheál Martin argued that the proposed deadline was not credible and that a Citizens' Assembly was not the right vehicle for the work.",
            "Government instead emphasised reconciliation, Shared Island cooperation and the Good Friday Agreement framework.",
        ],
        "kind": "body",
    },
    {
        "title": "What does the 69–79 vote tell us?",
        "kicker": "A ten-vote margin",
        "body": [
            "The Dáil narrowly rejected this proposed statutory planning process.",
            "It does not mean 69 TDs supported Irish unity, 79 opposed it, or that the Dáil voted against reunification itself.",
        ],
        "kind": "result",
    },
]


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def lines_for(text: str, width: int) -> list[str]:
    return wrap(text, width=width, break_long_words=False, break_on_hyphens=False)


def draw_wrapped(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], *, width_chars: int, size: int, bold: bool = False, fill: str = TEXT, spacing: int = 12) -> int:
    x, y = xy
    f = font(size, bold)
    for line in lines_for(text, width_chars):
        draw.text((x, y), line, font=f, fill=fill)
        y += size + spacing
    return y


def base(title: str, kicker: str) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    draw.text((LEFT, 66), "EIREPOLITIC", font=font(20, True), fill=ACCENT)
    y = draw_wrapped(draw, title, (LEFT, 124), width_chars=30, size=58, bold=True, spacing=6)
    draw.rectangle((LEFT, y + 18, RIGHT, y + 22), fill=ACCENT)
    draw.text((LEFT, y + 48), kicker.upper(), font=font(20, True), fill=MUTED)
    return image, draw, y + 102


def footer(draw: ImageDraw.ImageDraw, text: str = "Source: Houses of the Oireachtas · EirePolitic division data") -> None:
    draw.line((LEFT, 1250, RIGHT, 1250), fill=GRID, width=2)
    draw.text((W // 2, 1284), text, font=font(18), fill=MUTED, anchor="mm")


def vote_bar(draw: ImageDraw.ImageDraw, top: int) -> None:
    total = 148
    bar_left, bar_right = 145, 935
    bar_w = bar_right - bar_left
    yes_w = int(bar_w * 69 / total)
    no_w = bar_w - yes_w
    draw.rounded_rectangle((bar_left, top, bar_left + yes_w, top + 86), radius=18, fill=YES)
    draw.rounded_rectangle((bar_left + yes_w, top, bar_right, top + 86), radius=18, fill=NO)
    draw.text((bar_left + yes_w // 2, top + 43), "69 Tá", font=font(31, True), fill=BG, anchor="mm")
    draw.text((bar_left + yes_w + no_w // 2, top + 43), "79 Níl", font=font(31, True), fill=BG, anchor="mm")
    draw.text((W // 2, top + 126), "10-vote margin", font=font(29, True), fill=TEXT, anchor="mm")


def render_slide(index: int, spec: dict, output: Path) -> None:
    image, draw, y = base(spec["title"], spec["kicker"])
    kind = spec["kind"]

    if kind == "cover":
        vote_bar(draw, max(y + 105, 460))
        draw.text((W // 2, 940), "Planning for Constitutional Change Bill 2026", font=font(29, True), fill=TEXT, anchor="mm")
        draw.text((W // 2, 996), "Second Stage", font=font(24), fill=MUTED, anchor="mm")

    elif kind == "flow":
        box_top = y + 45
        for idx, step in enumerate(spec["steps"]):
            draw.rounded_rectangle((180, box_top, 900, box_top + 116), radius=18, outline=ACCENT, width=3)
            draw.text((W // 2, box_top + 58), step, font=font(27, True), fill=TEXT, anchor="mm")
            if idx < len(spec["steps"]) - 1:
                draw.line((W // 2, box_top + 116, W // 2, box_top + 158), fill=ACCENT, width=4)
                draw.polygon([(W // 2 - 9, box_top + 149), (W // 2 + 9, box_top + 149), (W // 2, box_top + 163)], fill=ACCENT)
            box_top += 164

    else:
        if kind == "result":
            vote_bar(draw, y + 20)
            y += 205
        else:
            y += 32
        for paragraph_index, paragraph in enumerate(spec.get("body", [])):
            emphasis = "not" in paragraph.lower() or paragraph_index == len(spec.get("body", [])) - 1 and kind == "result"
            draw.rounded_rectangle((LEFT, y, RIGHT, y + 6), radius=3, fill=ACCENT if emphasis else GRID)
            y += 28
            y = draw_wrapped(draw, paragraph, (LEFT, y), width_chars=43, size=31, bold=emphasis, fill=TEXT, spacing=11)
            y += 34

    footer(draw)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def render_contact_sheet(slides: list[Path], output: Path) -> None:
    thumb_w = 360
    thumb_h = 450
    gap = 28
    margin = 40
    label_h = 34
    cols = 3
    rows = 2
    sheet_w = margin * 2 + cols * thumb_w + (cols - 1) * gap
    sheet_h = margin * 2 + rows * (thumb_h + label_h) + (rows - 1) * gap
    sheet = Image.new("RGB", (sheet_w, sheet_h), "#e9e6df")
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(slides):
        with Image.open(path) as im:
            thumb = im.convert("RGB").resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        row, col = divmod(i, cols)
        x = margin + col * (thumb_w + gap)
        y = margin + row * (thumb_h + label_h + gap)
        sheet.paste(thumb, (x, y))
        draw.text((x + thumb_w // 2, y + thumb_h + 8), f"Slide {i + 1}", font=font(20, True), fill="#1d1d1b", anchor="ma")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def render_all(output_dir: Path) -> list[Path]:
    outputs = []
    for idx, spec in enumerate(SLIDES, start=1):
        path = output_dir / f"slide_{idx:02d}.png"
        render_slide(idx, spec, path)
        outputs.append(path)
    render_contact_sheet(outputs, output_dir / "contact_sheet.png")
    return outputs


if __name__ == "__main__":
    out = Path("artifacts/instagram/constitutional_change_close_vote_v1")
    rendered = render_all(out)
    for path in rendered:
        print(path)
    print(out / "contact_sheet.png")
