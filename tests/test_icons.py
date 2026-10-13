"""Icon set contracts: one consistent line set, every nav item drawn, no text glyphs."""
import re
from pathlib import Path

from bs4 import BeautifulSoup
from fasthtml.common import to_xml

import integrations
from web.design import ICON_PATHS
from web.public import landing_page, workspace_page

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static/app.js").read_text(encoding="utf-8")


def _js_object(name):
    body = re.search(rf"const {name} = \{{(.*?)\n  \}};", APP_JS, re.S).group(1)
    return dict(re.findall(r'"?([\w-]+)"?:\s*\n?\s*"([^"]+)"', body))


ICONS = _js_object("ICONS")
NAV_ICONS = _js_object("NAV_ICONS")


def test_every_navigation_item_has_its_own_icon():
    shell = BeautifulSoup(str(to_xml(workspace_page({"name": "Synthetic user"}))), "html.parser")
    views = [a["data-view"] for a in shell.select(".app-nav")]
    assert views and set(views) == set(NAV_ICONS)
    assert all(NAV_ICONS[view] in ICONS for view in views)
    # Distinct drawings, so no two destinations look alike.
    assert len({NAV_ICONS[view] for view in views}) == len(views)


def test_icons_share_one_drawing_style():
    assert re.search(r'stroke-width="1\.75" stroke-linecap="round" stroke-linejoin="round"', APP_JS)
    assert 'stroke-width="1.7"' not in APP_JS
    # The server-rendered subset draws exactly the same paths as the portal set.
    assert all(ICONS[name] == path for name, path in ICON_PATHS.items())
    for path in ICONS.values():
        numbers = [float(n) for n in re.findall(r"-?\d*\.?\d+", path)]
        assert all(-24 <= n <= 24 for n in numbers)


def test_no_text_glyphs_stand_in_for_icons():
    sources = [ROOT / "static/app.js", ROOT / "web/public.py", *sorted((ROOT / "web/locales").glob("*.json"))]
    for source in sources:
        assert not re.search("[☰✓✗✕✔↗]", source.read_text(encoding="utf-8")), source.name
    page = BeautifulSoup(str(landing_page()), "html.parser")
    assert len(page.select(".lh-mark svg")) == 8
    shell = BeautifulSoup(str(to_xml(workspace_page({"name": "Synthetic user"}))), "html.parser")
    assert shell.select_one("#menu-toggle svg")
    assert shell.select_one('link[rel="apple-touch-icon"]')["href"] == "/static/brand/apple-touch-icon.png"
    assert (ROOT / "static/brand/apple-touch-icon.png").stat().st_size < 4096


def test_integration_logos_exist_and_created_tiles_are_outlined():
    official = {"quickbooks.svg", "xero.svg", "merit-aktiva.svg"}
    for item in integrations.CATALOGUE:
        path = ROOT / item.logo.lstrip("/")
        assert path.is_file(), item.logo
        svg = path.read_text(encoding="utf-8")
        assert "<text" not in svg and "Arial" not in svg, path.name
        if path.name not in official:
            assert 'viewBox="0 0 64 64"' in svg and "<title>" in svg, path.name
            assert "#7c3aed" not in svg, path.name  # never paint other companies in the brand violet
