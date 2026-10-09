"""Build the FastAccounts user guide (HTML, PDF, PPTX) in English and Estonian.

Copied from FastShop's scripts/build_user_guide.py (FastClinic pattern): one
Markdown source per language, pandoc -> HTML, WeasyPrint -> landscape PDF with
text on the left and the screenshot on the right, python-pptx -> matching deck.
Bilingual editions follow FastERP's `_ee` convention, here suffixed `_et`.

Requires pandoc, pdfinfo (poppler) and `pip install -r requirements-docs.txt`.
Run: .venv/bin/python -m scripts.build_user_guide
Screenshots come from scripts/capture_user_guide.py (screenshots/en, screenshots/et).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_guide_pptx import parse_slides  # noqa: E402

DOCS = ROOT / "docs"
VERSION, GUIDE_DATE = (ROOT / "VERSION").read_text().split()[:2]
EDITIONS = {
    "en": ("USER_GUIDE.md", "", "FastAccounts — User Guide"),
    "et": ("USER_GUIDE_et.md", "_et", "FastAccounts — kasutusjuhend"),
}


def _weasyprint() -> str:
    local = Path(sys.executable).with_name("weasyprint")
    return str(local) if local.is_file() else "weasyprint"


def build(lang: str) -> dict:
    source_name, suffix, title = EDITIONS[lang]
    markdown = (DOCS / source_name).read_text()
    slides = parse_slides(markdown)
    for slide in slides:
        if slide["image"] and not (DOCS / slide["image"]).is_file():
            raise RuntimeError("Missing guide screenshot: " + slide["image"])
        if slide["image"] and f"/screenshots/{lang}/" not in slide["image"]:
            raise RuntimeError(f"{source_name} uses a screenshot from another language: {slide['image']}")
    base = DOCS / f"fastaccounts_user_guide_{GUIDE_DATE}{suffix}"
    snapshot = base.with_suffix(".md")
    snapshot.write_text(markdown)
    html = base.with_suffix(".html")
    subprocess.run(["pandoc", snapshot.name, "-s", "--from=markdown-implicit_figures",
                    "--css", "assets/guide.css", "--metadata", f"pagetitle={title}",
                    "--metadata", f"lang={lang}", "-o", html.name], cwd=DOCS, check=True)
    subprocess.run([_weasyprint(), "--base-url", str(DOCS) + "/", str(html), str(base.with_suffix(".pdf"))],
                   check=True)
    footer = (f"FastAccounts · {'kasutusjuhend' if lang == 'et' else 'User guide'} · "
              f"v{VERSION} · {GUIDE_DATE} · fastaccounts.org")
    subprocess.run([sys.executable, str(ROOT / "scripts/build_guide_pptx.py"), str(snapshot),
                    str(base.with_suffix(".pptx")), title],
                   env=os.environ | {"GUIDE_FOOTER": footer}, check=True)
    info = subprocess.check_output(["pdfinfo", str(base.with_suffix(".pdf"))], text=True)
    pages = int(re.search(r"^Pages:\s+(\d+)", info, re.M).group(1))
    if pages != len(slides):
        raise RuntimeError(f"{lang}: layout overflow, PDF {pages} pages vs {len(slides)} source slides")
    return {"lang": lang, "pages_and_slides": pages, "base": str(base.relative_to(ROOT)),
            "images": sum(bool(s["image"]) for s in slides)}


def main() -> None:
    for lang in sys.argv[1:] or EDITIONS:
        print(build(lang))


if __name__ == "__main__":
    main()
