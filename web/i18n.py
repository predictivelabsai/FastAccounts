"""Checked-in public-site translations and session language selection."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


DEFAULT_LANG = "en"
LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "native": "English", "flag": "🇬🇧"},
    "et": {"name": "Estonian", "native": "Eesti", "flag": "🇪🇪"},
    "lv": {"name": "Latvian", "native": "Latviešu", "flag": "🇱🇻"},
    "lt": {"name": "Lithuanian", "native": "Lietuvių", "flag": "🇱🇹"},
}
SUPPORTED_LANGS = frozenset(LANGUAGES)
LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, Any]:
    """Load one complete, version-controlled catalogue."""
    code = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    try:
        data = json.loads((LOCALES_DIR / f"{code}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        if code == DEFAULT_LANG:
            return {}
        return catalog(DEFAULT_LANG)
    return data if isinstance(data, dict) else {}


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Resolve a dotted catalogue key, falling back safely to English."""
    def resolve(source: dict[str, Any]) -> Any:
        value: Any = source
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    value = resolve(catalog(lang))
    if not isinstance(value, str):
        value = resolve(catalog(DEFAULT_LANG))
    return value if isinstance(value, str) else key


def integration_copy(lang: str, key: str) -> dict[str, Any]:
    """Return translated public copy for one known integration."""
    fallback = catalog(DEFAULT_LANG).get("integrations", {}).get("items", {}).get(key, {})
    translated = catalog(lang).get("integrations", {}).get("items", {}).get(key, {})
    return translated if isinstance(translated, dict) else fallback


def detect_language(request) -> str:
    """Choose the highest-quality supported browser language."""
    header = (getattr(request, "headers", {}) or {}).get("accept-language", "")
    preferences: list[tuple[float, int, str]] = []
    for index, item in enumerate(header.split(",")):
        parts = item.strip().split(";")
        code = parts[0].split("-")[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            parameter = parameter.strip()
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        preferences.append((quality, -index, code))
    for quality, _, code in sorted(preferences, reverse=True):
        if quality > 0 and code in SUPPORTED_LANGS:
            return code
    return DEFAULT_LANG


def get_lang(session: dict[str, Any], request=None) -> str:
    code = str(session.get("lang") or "").lower()
    if code in SUPPORTED_LANGS:
        return code
    code = detect_language(request) if request is not None else DEFAULT_LANG
    session["lang"] = code
    return code


def set_lang(session: dict[str, Any], lang: str) -> str:
    code = (lang or "").lower()
    if code in SUPPORTED_LANGS:
        session["lang"] = code
    return get_lang(session)
