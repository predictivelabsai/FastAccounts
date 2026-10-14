"""Brand contracts and offline light/dark browser checks."""
import json
from pathlib import Path
import re

from bs4 import BeautifulSoup
from fasthtml.common import to_xml
import pytest

from web.design import DESIGN_CSS, Product, accent_style
from web.public import PUBLIC_CSS, landing_page, workspace_page

ROOT = Path(__file__).resolve().parents[1]
APP_CSS = (ROOT / "static/app.css").read_text(encoding="utf-8")


def test_primary_mark_and_favicon():
    favicon = (ROOT / "static/favicon.svg").read_text(encoding="utf-8")
    assert "#7c3aed" in favicon
    assert favicon == (ROOT / "static/brand/fastaccounts-mark.svg").read_text(encoding="utf-8")
    for rendered in (str(landing_page()), str(to_xml(workspace_page({"name": "Synthetic user"})))):
        page = BeautifulSoup(rendered, "html.parser")
        assert page.select_one('img[src="/static/brand/fastaccounts-mark.svg"]')
        assert page.select_one('meta[name="theme-color"]')["content"] == "#150a2c"
        assert page.select_one('link[href^="/static/fonts/fonts.css?v="]')


@pytest.mark.parametrize("css", [DESIGN_CSS + PUBLIC_CSS, APP_CSS], ids=["public", "portal"])
def test_complete_variables_and_no_decorative_gradients(css):
    assert "linear-gradient(135deg" not in css
    assert "radial-gradient" not in css
    defined = set(re.findall(r"(--[\w-]+)\s*:", css))
    # An undefined property is allowed only when var() supplies a fallback.
    required = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))
    assert not required - defined
    assert '@media (prefers-color-scheme: dark)' in css
    assert ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="dark"]' in css


@pytest.mark.parametrize("css", [DESIGN_CSS, APP_CSS], ids=["public", "portal"])
def test_canonical_token_values(css):
    source = json.loads((ROOT / "docs/brand/tokens.json").read_text(encoding="utf-8"))
    light = css.split("@media", 1)[0]
    dark = css.split(':root[data-theme="dark"]', 1)[1].split("}", 1)[0]
    for token in source["color"]["tokens"] + source["shadow"]["tokens"]:
        values = token["value"]
        if isinstance(values, dict):
            assert f'--{token["name"]}: {values["light"]};' in light
            assert f'--{token["name"]}: {values["dark"]};' in dark
        else:
            assert f'--{token["name"]}: {values};' in light


def test_sibling_product_accent_override():
    override = str(accent_style(Product(accent="#123456", accent_strong="#234567")))
    assert "--accent:#123456" in override
    assert "--accent-hover:#234567" in override
    assert "--accent-text:#234567" in override


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_public_pages_and_portal_at_mobile_width(theme):
    playwright = pytest.importorskip("playwright.sync_api")
    from web import public

    pages = [public.landing_page(), public.integrations_page(), public.login_page(),
             public.login_page(tab="register"), public.mfa_page(),
             public.password_token_page("reset", "synthetic-token"),
             public.security_page(), public.privacy_page(), public.terms_page(),
             public.about_page(), public.contact_page(), public.roadmap_page(), public.changelog_page()]
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme=theme)

        def respond(route):
            path = route.request.url.split("brand.test", 1)[-1].split("?", 1)[0]
            if path.startswith("/static/"):
                file = ROOT / path.lstrip("/")
                if file.is_file():
                    return route.fulfill(path=str(file))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://brand.test/")
        for rendered in pages:
            page.set_content(str(to_xml(rendered)))
            page.evaluate("document.fonts.ready")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == theme
            assert page.locator(".fs-brand img").first.evaluate("img => img.complete && img.naturalWidth > 0")
        page.set_content(str(to_xml(public.landing_page())))
        page.locator(".fs-menu-toggle").click()
        assert page.locator(".fs-nav-links").is_visible()
        page.keyboard.press("Escape")
        assert not page.locator(".fs-nav-links").is_visible()
        # An explicit preference takes precedence over the OS theme.
        other = "light" if theme == "dark" else "dark"
        page.evaluate("theme => document.documentElement.dataset.theme = theme", other)
        assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == other
        shell = str(to_xml(workspace_page({"name": "Synthetic user"})))
        page.set_content(shell)
        page.add_style_tag(content=APP_CSS)
        page.locator("#app-content").evaluate("el => el.innerHTML = '<section class=card><h1>Invoices</h1><input value=123><select><option>Draft</option></select><div class=empty>Nothing to review</div><table><tr class=total><td class=numeric>123.00</td></tr></table></section>'")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator(".card").evaluate("el => getComputedStyle(el).backgroundColor") == ("rgb(23, 16, 41)" if theme == "dark" else "rgb(255, 255, 255)")
        browser.close()

@pytest.mark.parametrize("lang", ["en", "et", "lv", "lt"])
def test_language_codes_and_short_hero_phrase(lang):
    from web import i18n
    page = BeautifulSoup(str(landing_page(lang)), "html.parser")
    assert page.select_one("#language-menu-button span").get_text() == lang.upper()
    assert i18n.LANGUAGES[lang]["name"] in page.select_one("#language-menu-button")["aria-label"]
    assert [el.get_text() for el in page.select(".language-flag")] == ["EN", "ET", "LV", "LT"]
    assert [el["aria-label"] for el in page.select(".language-option")] == ["English", "Estonian", "Latvian", "Lithuanian"]
    assert len(page.select_one(".lh-hi").get_text().split()) <= 2


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hero_and_overview_polish_in_browser(theme, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    organisations = [
        {"id": "synthetic-ee", "name": "Synthetic Eesti OÜ", "country_code": "EE", "base_currency": "EUR"},
        {"id": "synthetic-uk", "name": "Synthetic UK Ltd", "country_code": "UK", "base_currency": "GBP"},
    ]
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme=theme)
        def respond(route):
            path = route.request.url.split("brand.test", 1)[-1].split("?", 1)[0]
            if path.startswith("/static/"):
                file = ROOT / path.lstrip("/")
                if file.is_file():
                    if file.suffix == ".js":
                        return route.fulfill(path=str(file), content_type="application/javascript; charset=utf-8")
                    return route.fulfill(path=str(file))
            if path.startswith("/api/"):
                data = {"csrf_token": "synthetic"} if path == "/api/csrf" else organisations if path == "/api/organisations" else []
                return route.fulfill(body=json.dumps(data), content_type="application/json")
            return route.fulfill(status=404)
        page.route("**/*", respond)
        page.goto("http://brand.test/")
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            for lang in ("en", "et", "lv", "lt"):
                page.set_content(str(to_xml(landing_page(lang))))
                page.evaluate("document.fonts.ready")
                span = page.locator(".lh-hi")
                assert span.evaluate("el => getComputedStyle(el).whiteSpace") == "nowrap"
                bounds = span.bounding_box()
                hero = page.locator("#hero").bounding_box()
                sub = page.locator(".lh-sub").bounding_box()
                assert 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= width
                assert bounds["y"] + bounds["height"] < sub["y"]
                assert bounds["y"] + bounds["height"] < hero["y"] + hero["height"]
                assert span.evaluate("el => getComputedStyle(el).backgroundSize") == "100% 2px, 100% 2px"
                ruling = page.locator("#hero").evaluate("el => getComputedStyle(el, '::after').backgroundImage")
                alpha = re.search(r"rgba\(244, 240, 255, ([0-9.]+)\)", ruling)
                assert alpha and float(alpha[1]) == pytest.approx(.045, abs=.003)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                page.screenshot(path=str(tmp_path / f"hero-{lang}-{width}-{theme}.png"), full_page=False)
            # Exercise the actual app script and overview, with synthetic offline API responses.
            shell = str(to_xml(workspace_page({"name": "Synthetic user"})))
            # Simulate a navigation group with no visible rows before JS initialisation.
            shell = shell.replace('data-view="accounting"', 'hidden="" data-view="accounting"')
            for view in ("cash-flow", "fixed-assets", "periods", "tax"):
                shell = shell.replace(f'data-view="{view}"', f'hidden="" data-view="{view}"')
            page.set_content(shell)
            page.locator(".client-book").first.wait_for()
            page.evaluate("document.fonts.ready")
            assert page.locator('.nav-group', has_text="Accounting").evaluate("el => el.hidden")
            assert not page.locator('.nav-group', has_text="Accounting").is_visible()
            for tag in page.locator(".client-book .country-badge").all():
                bounds = tag.bounding_box()
                assert bounds["height"] == 20 and bounds["width"] < 36
                assert tag.evaluate("el => getComputedStyle(el).justifySelf") == "end"
            if width == 390:
                assert page.locator(".app-sidebar").evaluate("el => getComputedStyle(el).boxShadow") == "none"
                page.locator("#menu-toggle").click()
                page.wait_for_timeout(250)
                assert page.locator(".app-sidebar").evaluate("el => getComputedStyle(el).boxShadow") != "none"
            else:
                assert page.locator(".app-sidebar").evaluate("el => getComputedStyle(el).borderRightWidth") == "1px"
            assert page.locator(".app-topbar").evaluate("el => getComputedStyle(el).borderBottomWidth") == "1px"
            for link in page.locator(".app-side-link").all():
                assert link.bounding_box()["height"] == 38
                assert link.locator("svg").bounding_box()["width"] == 18
                assert link.evaluate("el => getComputedStyle(el).paddingLeft") == page.locator(".app-nav").first.evaluate("el => getComputedStyle(el).paddingLeft")
            page.screenshot(path=str(tmp_path / f"portal-{width}-{theme}.png"), full_page=False)
            if width == 390:
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
                page.screenshot(path=str(tmp_path / f"portal-{width}-{theme}-closed.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()
