"""Public shell, integration catalogue, auth guard, and health checks."""
from __future__ import annotations

from starlette.testclient import TestClient
from bs4 import BeautifulSoup
import pytest

import integrations
from web import i18n
from web.public import integrations_page, landing_page, login_page, workspace_page
from web_app import app


client = TestClient(app)


def test_landing_has_primary_product_and_sign_in_routes():
    rendered = str(landing_page())
    assert "Bookkeeping that stays clear" in rendered
    assert 'href="/integrations"' in rendered
    assert 'href="/login"' in rendered
    assert "UK and Estonian VAT" in rendered


@pytest.mark.parametrize("lang", ["en", "et", "lv", "lt"])
def test_landing_template_sections_and_translated_content(lang):
    page = BeautifulSoup(str(landing_page(lang)), "html.parser")
    main = page.select_one("main")
    sections = main.find_all("section", recursive=False)
    assert [section.get("id") for section in sections] == [
        "hero", "dashboard", None, "why", "process", "comparison",
        "bureaus", "pricing", "product-facts", "faq", "get-started",
    ]
    hero = page.select_one("#hero")
    assert i18n.t("landing.hero_h1", lang) in hero.h1.get_text()
    assert hero.select_one("h1 .lh-hi").get_text() == i18n.t("landing.hero_highlight", lang)
    assert hero.select_one('a[href="/login"]').get_text() == i18n.t("landing.hero_cta", lang)
    mock = page.select_one("#dashboard .lh-mock")
    assert mock.has_attr("inert") and mock["aria-hidden"] == "true"
    assert i18n.t("landing.mock_sample", lang) in mock.get_text()
    assert len(mock.select(".lh-kpi")) == 3
    glass = page.select("#dashboard .lh-glass")
    assert len(glass) == 3
    for card, kind in zip(glass, ("bank", "invoice", "tax")):
        assert card.has_attr("inert") and card["aria-hidden"] == "true"
        assert card.small.get_text() == i18n.t(f"landing.float_{kind}", lang)
    steps = page.select("#process ol > li")
    assert len(steps) == 4
    for n, step in enumerate(steps, 1):
        assert step.h3.get_text() == i18n.t(f"landing.step{n}_title", lang)
        assert step.p.get_text() == i18n.t(f"landing.step{n}_body", lang)
        assert step.select_one(".lh-step-number").get_text() == f"{n:02d}"
    for way in ("old", "new"):
        panel = page.select_one(f"#comparison .{way}")
        assert panel.h3.get_text() == i18n.t(f"landing.{way}_title", lang)
        assert len(panel.select("li")) == 4
        for n, item in enumerate(panel.select("li"), 1):
            assert i18n.t(f"landing.{way}{n}", lang) in item.get_text()
    facts = page.select("#product-facts dl > div")
    assert [(item.dt.get_text(), item.dd.get_text()) for item in facts] == [
        (i18n.t(label, lang), i18n.t(value, lang)) for label, value in (
            ("landing.stats_languages", "landing.stats_languages_value"),
            ("landing.stats_markets", "landing.stats_markets_value"),
            ("pricing.byoc_eyebrow", "pricing.byoc_price"),
            ("pricing.hosted_eyebrow", "pricing.hosted_price"),
        )
    ]
    assert len(page.select("#why .lh-feat")) == 3
    assert len(page.select("#bureaus .lh-stat-item")) == 4
    assert len(page.select("#pricing .lh-price")) == 2
    assert i18n.t("pricing.hosted_price", lang) in page.select_one(".lh-price.feature").get_text()
    assert len(page.select("#faq .lh-faq")) == 5
    for n in range(1, 6):
        faq = page.select("#faq details.lh-faq")[n - 1]
        assert faq.summary.get_text() == i18n.t(f"landing.faq{n}_q", lang)
        assert faq.p.get_text() == i18n.t(f"landing.faq{n}_a", lang)
        assert faq["name"] == "faq"


@pytest.mark.parametrize("lang", ["en", "et", "lv", "lt"])
@pytest.mark.parametrize("render,current", [(landing_page, "/"), (integrations_page, "/integrations"), (login_page, "/login")])
def test_public_pages_share_accessible_localized_shell(render, current, lang):
    page = BeautifulSoup(str(render(lang=lang)), "html.parser")
    assert page.html["lang"] == lang
    assert page.select_one('.fs-skip[href="#main-content"]')
    assert page.select_one("main#main-content")
    assert page.select_one(".fs-nav .fs-brand").get_text() == "FFastAccounts"
    assert page.select_one(".fs-mark").get_text() == "F"
    assert not page.select_one(".fs-mark svg")
    assert len(page.select("#language-menu-button")) == 1
    assert len(page.select("#language-menu")) == 1
    assert len(page.select('[role="menuitem"]')) == 4
    assert page.select_one(f'a[href="/set-lang/et?next={current}"]')
    assert page.select_one('link[href="/static/fonts/fonts.css"]')
    assert len(page.select('link[rel="preload"][as="font"]')) == 2
    assert i18n.t("footer.tagline", lang) in page.select_one(".fs-footer").get_text()
    assert page.select_one('.fs-footer a[href="/healthz"]')
    assert "Powered by Predictive Labs" not in page.get_text()
    if current == "/login":
        assert page.select_one('a[href="/auth/google"]')
    elif current == "/integrations":
        assert len(page.select(".integration")) == len(integrations.CATALOGUE)


def test_integration_catalogue_lists_platforms_agents_and_bank_plan():
    rendered = str(integrations_page())
    for name in (
        "QuickBooks Online",
        "Xero",
        "Merit Aktiva",
        "HMRC Making Tax Digital",
        "Estonian Tax and Customs Board",
        "Open banking",
    ):
        assert name in rendered
    for item in integrations.CATALOGUE:
        assert item.status not in rendered
    assert "No provider below is connected by default" in rendered
    assert "Configured per object" in rendered


def test_hr_software_catalogue_is_complete_and_renders_in_every_locale():
    expected_keys = {
        "file_import", "fasthr", "bamboohr", "personio", "hibob", "zoho_people", "employment_hero",
        "workday", "hrmaster", "gusto", "rippling", "deel", "odoo_hr",
        "persona_fujitsu", "wemply", "hours24", "yester", "hrm4baltics",
        "merit_palk", "taavi_palk", "andevis", "eeva",
    }
    hr_entries = [item for item in integrations.CATALOGUE if item.category == "HR software"]

    assert {item.key for item in hr_entries} == expected_keys
    assert len(hr_entries) == 22
    roadmap_entries = [
        item for item in hr_entries
        if item.key not in {"fasthr", "file_import", "bamboohr", "personio"}
    ]
    assert all(item.status == "Roadmap · no adapter yet" for item in roadmap_entries)
    assert all(item.direction == "Import first · export by policy" for item in roadmap_entries)
    assert all(item.ownership == "Configured per object" for item in roadmap_entries)
    fasthr = next(item for item in hr_entries if item.key == "fasthr")
    assert fasthr.status == "Adapter ready"
    assert fasthr.direction == "Import · employee master data"
    assert fasthr.ownership == "FastHR remains source"
    for key in ("bamboohr", "personio"):
        documented = next(item for item in hr_entries if item.key == key)
        assert documented.status == "Documented contract · not live-verified"
        assert documented.direction.startswith("Import ·")
        assert documented.ownership.endswith("remains source")
    file_import = next(item for item in hr_entries if item.key == "file_import")
    assert file_import.status == "Adapter ready"
    assert file_import.direction == "Import · uploaded files"
    assert file_import.ownership == "Uploaded export remains source"

    for lang in ("en", "et", "lv", "lt"):
        page = BeautifulSoup(str(integrations_page(lang)), "html.parser")
        localized_category = i18n.integration_copy(lang, "bamboohr")["category"]
        cards = [
            card for card in page.select(".integration")
            if card.select_one(".category").get_text(strip=True) == localized_category
        ]
        assert len(cards) == 22
        rendered_names = {card.h2.get_text(strip=True) for card in cards}
        assert rendered_names == {
            i18n.integration_copy(lang, item.key)["name"] for item in hr_entries
        }


def test_integration_status_remains_available_to_internal_workspace():
    response = client.get("/api/integrations", headers={"X-Test-User": "viewer@test.invalid"})
    assert response.status_code == 200
    assert [item["status"] for item in response.json()] == [
        item.status for item in integrations.CATALOGUE
    ]


def test_provider_logos_have_accessible_alt_text_and_local_assets_resolve():
    rendered = str(integrations_page())
    for item in integrations.CATALOGUE:
        assert f'alt="{item.logo_alt}"' in rendered
        if item.logo.startswith("/static/"):
            response = client.get(item.logo)
            assert response.status_code == 200
            assert "image/svg+xml" in response.headers["content-type"]


def test_login_explains_disabled_google_configuration(monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    rendered = str(login_page())
    assert "Google sign-in is not configured" in rendered
    response = client.get("/auth/google", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=")


def test_google_callback_rejects_missing_or_invalid_state_without_network():
    response = client.get(
        "/auth/google/callback?code=unused&state=invalid",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "state+was+invalid" in response.headers["location"]


def test_workspace_requires_authentication():
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


@pytest.mark.parametrize("lang", ["en", "et", "lv", "lt"])
def test_workspace_shell_renders_localized_integrations_entry(lang):
    page = BeautifulSoup(
        str(workspace_page({"email": "owner@example.test"}, lang)),
        "html.parser",
    )
    entry = page.select_one('.app-nav[data-view="integrations"]')
    assert entry is not None
    assert entry.get_text(strip=True) == i18n.t("nav.integrations", lang)
    assert entry["href"] == "#integrations"
    assert page.select_one("#workspace-app")["data-lang"] == lang
    assert page.select_one('script[src="/static/app.js"]')
    catalogue_script = page.find("script", src=False).get_text()
    assert '"Configure, test and review data for this client."' in catalogue_script
    assert "stored-token" not in catalogue_script


def test_demo_login_displays_demo_user_in_workspace_sidebar(monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    with TestClient(app) as demo_client:
        response = demo_client.get("/auth/test")
    assert response.status_code == 200
    assert '<strong>Demo Kasutaja</strong>' in response.text


def test_health_reports_every_connector_as_non_live():
    with TestClient(app) as live_client:
        response = live_client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["product"] == "FastAccounts"
    assert payload["integrations"] == len(integrations.CATALOGUE)
    assert payload["live_integrations"] == 0
    assert payload["database"]["status"] == "ok"
    assert payload["database"]["migrations"] == 9


def test_public_violet_tokens_and_new_locale_keys():
    from web.design import DESIGN_CSS, FASTPRODUCT
    from web.public import PUBLIC_CSS

    assert FASTPRODUCT.accent == "#7c3aed"
    assert FASTPRODUCT.accent_strong == "#5b21b6"
    for token in ("--on-accent:#ffffff", "--ink:#14062b", "--paper:#faf9fc",
                  "--text:#1c1333", "--muted:#6b6580", "--line:#e8e5f0"):
        assert token in DESIGN_CSS
    assert "#c2f24f" not in DESIGN_CSS + PUBLIC_CSS
    assert "linear-gradient(135deg,#6d28d9 0%,#7c3aed 45%,#4f46e5 100%)" in PUBLIC_CSS
    keys = ["process_title", "process_body", "comparison_title", "old_title", "new_title",
            "stats_label", "stats_languages", "stats_languages_value", "stats_markets",
            "stats_markets_value"]
    keys += [f"float_{kind}" for kind in ("bank", "invoice", "tax")]
    keys += [f"step{n}_{part}" for n in range(1, 5) for part in ("title", "body")]
    keys += [f"{way}{n}" for way in ("old", "new") for n in range(1, 5)]
    for lang in ("en", "et", "lv", "lt"):
        catalog = i18n.catalog(lang)["landing"]
        assert all(catalog.get(key) for key in keys)
