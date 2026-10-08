"""Public translation catalogues and language-selection behaviour."""
from __future__ import annotations

from types import SimpleNamespace

from starlette.testclient import TestClient

from web import i18n
from web.public import integrations_page, landing_page
from web_app import app


def _schema(value):
    if isinstance(value, dict):
        return {key: _schema(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_schema(child) for child in value]
    return str


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)
    else:
        yield value


def _request(accept_language: str = ""):
    return SimpleNamespace(headers={"accept-language": accept_language})


def test_all_public_translation_catalogues_are_complete_and_nonempty():
    english_schema = _schema(i18n.catalog("en"))
    assert english_schema
    for lang in i18n.LANGUAGES:
        catalogue = i18n.catalog(lang)
        assert _schema(catalogue) == english_schema
        assert all(isinstance(value, str) and value.strip() for value in _strings(catalogue))


def test_browser_language_detection_honours_quality_region_and_fallback():
    assert i18n.detect_language(_request("et-EE,et;q=0.9,en;q=0.8")) == "et"
    assert i18n.detect_language(_request("de-DE;q=1,lv-LV;q=0.7")) == "lv"
    assert i18n.detect_language(_request("es-ES,zh;q=0.8")) == "en"
    assert i18n.detect_language(_request("lt-LT;q=0,et-EE;q=0.6")) == "et"


def test_workspace_unmatched_status_translations():
    for lang, expected in {
        "en": "Unmatched", "et": "Vastendamata",
        "lv": "Nesalīdzināts", "lt": "Nesulygintas",
    }.items():
        assert i18n.catalog(lang)["workspace"]["Unmatched"] == expected


def test_language_dropdown_lists_four_locales_and_preserves_current_route():
    rendered = str(integrations_page("lv"))
    assert '<html lang="lv">' in rendered
    assert rendered.count('role="menuitem"') == 4
    assert 'aria-label="Izvēlēties valodu"' in rendered
    assert 'href="/set-lang/et?next=/integrations"' in rendered
    assert 'href="/set-lang/lt?next=/integrations"' in rendered


def test_each_baltic_language_renders_translated_public_and_provider_copy():
    expectations = {
        "et": ("Raamatupidamine, mis püsib selge", "Eesti Maksu- ja Tolliamet"),
        "lv": ("Grāmatvedība, kas paliek skaidra", "Igaunijas Nodokļu un muitas pārvalde"),
        "lt": ("Buhalterinė apskaita, kuri išlieka aiški", "Estijos mokesčių ir muitų valdyba"),
    }
    for lang, (headline, provider) in expectations.items():
        assert headline in str(landing_page(lang))
        assert provider in str(integrations_page(lang))


def test_fasthr_catalogue_copy_exists_in_all_locales():
    descriptions = {
        "en": "FastHR does not contain an Estonian personal identification code.",
        "et": "Isikukood ei sisaldu FastHR-is.",
        "lv": "FastHR nesatur Igaunijas personas kodu.",
        "lt": "FastHR nėra Estijos asmens kodo.",
    }
    for lang, personal_data_note in descriptions.items():
        copy = i18n.integration_copy(lang, "fasthr")
        assert copy["name"] == "FastHR"
        assert personal_data_note in copy["description"]
        assert copy["direction"]
        assert copy["ownership"]
        assert "FastHR" in str(integrations_page(lang))


def test_language_selection_persists_in_signed_session():
    with TestClient(app) as client:
        selected = client.get("/set-lang/et?next=/integrations", follow_redirects=False)
        assert selected.status_code == 303
        assert selected.headers["location"] == "/integrations"
        rendered = client.get("/integrations")
        assert rendered.status_code == 200
        assert '<html lang="et">' in rendered.text
        assert "Ühenda tööriistad" in rendered.text


def test_language_return_path_rejects_external_redirects():
    with TestClient(app) as client:
        response = client.get(
            "/set-lang/lt?next=https://example.com/steal",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
