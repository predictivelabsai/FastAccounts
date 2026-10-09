"""Documentation checks for the bilingual user guide (no browser, no network)."""
import re
from pathlib import Path

import pytest

from scripts.build_guide_pptx import parse_slides

ROOT = Path(__file__).resolve().parents[1]
GUIDE_DATE = (ROOT / "VERSION").read_text(encoding="utf-8").split()[1]
SOURCES = {"en": "USER_GUIDE.md", "et": "USER_GUIDE_et.md"}


def _slides(lang):
    return parse_slides((ROOT / "docs" / SOURCES[lang]).read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", SOURCES)
def test_guide_structure_contents_and_screenshots(lang):
    markdown = (ROOT / "docs" / SOURCES[lang]).read_text(encoding="utf-8")
    slides = _slides(lang)
    assert len(slides) == 40 and slides[0]["kind"] == "cover"
    sections = [i + 1 for i, slide in enumerate(slides) if slide["kind"] == "section"]
    assert sections == [3, 9, 16, 20, 30, 38]
    # The contents table's page ranges start at each section divider.
    starts = [int(m) for m in re.findall(r"^\| \*\*0\d · .+?\*\* \| (\d+)–\d+ \|", markdown, re.M)]
    assert starts == sections
    images = [slide["image"] for slide in slides if slide["image"]]
    assert len(images) == 29
    for image in images:
        assert image.startswith(f"../screenshots/{lang}/"), image
        assert (ROOT / "docs" / image).is_file(), image
    for target in re.findall(r"\]\(([^)]+)\)", markdown):
        if not target.startswith(("https://", "http://", "#")):
            assert (ROOT / "docs" / target).is_file(), target


def test_editions_match_slide_for_slide():
    en, et = _slides("en"), _slides("et")
    assert [s["kind"] for s in en] == [s["kind"] for s in et]
    assert [s["image"] and s["image"].replace("/en/", "/") for s in en] == [
        s["image"] and s["image"].replace("/et/", "/") for s in et]
    captured = {lang: sorted(p.name for p in (ROOT / "screenshots" / lang).glob("*.png")) for lang in SOURCES}
    assert captured["en"] == captured["et"] and len(captured["en"]) == 28


@pytest.mark.parametrize("lang,suffix", [("en", ""), ("et", "_et")])
def test_dated_edition_matches_source(lang, suffix):
    dated = ROOT / "docs" / f"fastaccounts_user_guide_{GUIDE_DATE}{suffix}.md"
    assert dated.read_text(encoding="utf-8") == (ROOT / "docs" / SOURCES[lang]).read_text(encoding="utf-8")
    for ext in (".html", ".pdf", ".pptx"):
        assert dated.with_suffix(ext).is_file()
