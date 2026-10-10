from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from instagram.renderer.template_renderer import render_template

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_PATH = ROOT / "instagram/templates/layouts/party_issue_monthly_profile_v2.json"
PROJECT_PATH = ROOT / "instagram/projects/party_issue_monthly_profile_v2/project.yml"


def test_party_speech_project_uses_dedicated_approved_layout() -> None:
    import yaml

    project = yaml.safe_load(PROJECT_PATH.read_text(encoding="utf-8"))
    assert project["render"]["outer_layout"] == "instagram/templates/layouts/party_issue_monthly_profile_v2.json"


def test_approved_layout_has_locked_accents_and_green_media_background() -> None:
    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    elements = {item["id"]: item for item in layout["elements"]}

    assert layout["width"] == 1080
    assert layout["height"] == 1350
    assert elements["title"]["style"]["align"] == "center"
    assert elements["title_rule"] == {
        "id": "title_rule",
        "type": "rectangle",
        "x": 112,
        "y": 174,
        "w": 856,
        "h": 5,
        "fill": "{palette.accent}",
    }
    assert elements["main_media"]["x"] == 24
    assert elements["main_media"]["y"] == 190
    assert elements["main_media"]["w"] == 1032
    assert elements["main_media"]["h"] == 1126
    assert elements["main_media"]["fit"] == "contain"
    assert elements["main_media"]["background"] == "{palette.background}"
    assert elements["main_media"]["radius"] == 0
    assert {"ornament_tl", "ornament_tr", "ornament_bl", "ornament_br"}.issubset(elements)


def test_rendered_analytical_wrapper_has_no_black_sidebars_and_keeps_accents(tmp_path: Path) -> None:
    chart = Image.new("RGB", (1032, 1210), "#0f2f24")
    chart_path = tmp_path / "chart.png"
    chart.save(chart_path)

    layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
    out = tmp_path / "slide.png"
    result = render_template(
        layout,
        {"slide_title": "Most Discussed Issues", "main_media": str(chart_path)},
        out,
    )
    assert result.warnings == []

    image = Image.open(out).convert("RGB")
    assert image.size == (1080, 1350)

    # These positions sat inside the dark side-padding of the generic content-card
    # layout that caused the September regression. The approved layout must keep
    # them on the same EirePolitic green as the chart/background.
    side_samples = [
        image.getpixel((90, 500)),
        image.getpixel((990, 500)),
        image.getpixel((90, 900)),
        image.getpixel((990, 900)),
    ]
    assert all(pixel == (15, 47, 36) for pixel in side_samples)

    # Locked gold title rule must be present.
    assert image.getpixel((540, 176)) == (216, 180, 95)

    # Corner ornaments must visibly alter the background near both top corners.
    background = (15, 47, 36)
    top_left_crop = image.crop((0, 0, 155, 155))
    top_right_crop = image.crop((925, 0, 1080, 155))
    assert any(pixel != background for pixel in top_left_crop.getdata())
    assert any(pixel != background for pixel in top_right_crop.getdata())
