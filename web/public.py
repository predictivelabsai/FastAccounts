"""Public FastAccounts landing, sign-in, and integration catalogue pages."""
from __future__ import annotations

import json
from urllib.parse import quote
from dataclasses import replace

from fasthtml.common import *

import integrations
import version
from .assets import STATIC_DIR, asset_url
from . import google_auth, i18n
from .design import (DESIGN_CSS, FONT_LINKS, FASTPRODUCT, MOBILE_NAV_JS,
                     accent_style, fs_button, fs_eyebrow, fs_icon, fs_nav, fs_footer)


PUBLIC_CSS = (STATIC_DIR / "public.css").read_text(encoding="utf-8")


def _language_switcher(lang: str, current: str):
    selected = i18n.LANGUAGES.get(lang, i18n.LANGUAGES[i18n.DEFAULT_LANG])
    return Div(
        Button(
            Span(selected["code"]),
            type="button",
            id="language-menu-button",
            aria_label=f"{i18n.t('language.choose', lang)}: {selected['name']}",
            aria_haspopup="true",
            aria_expanded="false",
            onclick="toggleLanguageMenu(event)",
            cls="language-trigger",
        ),
        Div(
            *[
                A(
                    Span(info["code"], cls="language-flag"),
                    Span(info["native"]),
                    href=f"/set-lang/{code}?next={quote(current, safe='/')}",
                    lang=code,
                    role="menuitem",
                    aria_label=info["name"],
                    aria_current="true" if code == lang else None,
                    cls=f"language-option{' active' if code == lang else ''}",
                )
                for code, info in i18n.LANGUAGES.items()
            ],
            id="language-menu",
            role="menu",
            cls="language-menu",
        ),
        cls="language-picker",
    )


def _nav(lang: str, current: str):
    T = lambda key: i18n.t(key, lang)
    return fs_nav(
        FASTPRODUCT,
        [(T("nav.product"), "/#why"), (T("nav.for_bureaus"), "/#bureaus"),
         (T("nav.integrations"), "/integrations"), (T("nav.pricing"), "/#pricing"),
         (T("nav.security"), "/security"), (T("nav.changelog"), "/changelog")],
        [_language_switcher(lang, current), fs_button(T("nav.sign_in"), "/login", "primary")],
        menu_label=T("nav.open_navigation"),
    )


def _footer(lang: str):
    T = lambda key: i18n.t(key, lang)
    return fs_footer(
        replace(FASTPRODUCT, tagline=T("footer.tagline")),
        [(T("footer.product"), [(T("nav.product"), "/#why"),
                                (T("nav.for_bureaus"), "/#bureaus"),
                                (T("footer.integrations"), "/integrations"),
                                (T("nav.pricing"), "/#pricing")]),
         (T("footer.trust"), [(T("footer.security"), "/security"),
                              (T("footer.privacy"), "/privacy"),
                              (T("footer.terms"), "/terms")]),
         (T("footer.company"), [(T("footer.about"), "/about"),
                                (T("footer.contact"), "/contact"),
                                (T("footer.roadmap"), "/roadmap"),
                                (T("footer.changelog"), "/changelog")]),
         (T("footer.resources"), [(T("footer.status"), "/healthz"),
                                  (T("footer.documentation"), f"{FASTPRODUCT.github_url}/tree/main/docs"),
                                  (T("footer.source"), FASTPRODUCT.github_url)])],
        T("footer.legal_entity"),
        [A(T("footer.contact_email"), href="mailto:info@predictivelabs.ai?subject=FastAccounts%20enquiry"),
         A(version.label(), href="/healthz", title=version.detail(), data_testid="app-version")],
        legal=T("footer.legal_notice"),
    )


def public_page(*content, title: str, current: str, lang: str):
    return Html(
        Head(
            Title(f"{title} · FastAccounts"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Meta(name="theme-color", content="#150a2c"),
            Meta(name="description", content=i18n.t("meta.description", lang)),
            Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Link(rel="apple-touch-icon", href="/static/brand/apple-touch-icon.png"),
            *FONT_LINKS,
            Link(rel="stylesheet", href=asset_url("design.css")),
            Link(rel="stylesheet", href=asset_url("public.css")),
            accent_style(FASTPRODUCT),
            Script(NotStr(MOBILE_NAV_JS)),
            Script(NotStr("""
                function closeLanguageMenu() {
                    const menu = document.getElementById('language-menu');
                    const button = document.getElementById('language-menu-button');
                    if (menu) menu.classList.remove('open');
                    if (button) button.setAttribute('aria-expanded', 'false');
                }
                function toggleLanguageMenu(event) {
                    event.stopPropagation();
                    const menu = document.getElementById('language-menu');
                    const button = document.getElementById('language-menu-button');
                    const opening = !menu.classList.contains('open');
                    menu.classList.toggle('open');
                    button.setAttribute('aria-expanded', opening ? 'true' : 'false');
                    if (opening) menu.querySelector('a').focus();
                }
                document.addEventListener('click', closeLanguageMenu);
                document.addEventListener('keydown', function(event) {
                    if (event.key === 'Escape') {
                        const wasOpen = document.getElementById('language-menu').classList.contains('open');
                        closeLanguageMenu();
                        const button = document.getElementById('language-menu-button');
                        if (button && wasOpen) {
                            event.stopPropagation();
                            button.focus();
                        }
                    }
                }, true);
            """)),
        ),
        Body(A(i18n.t("nav.skip_content", lang), href="#main-content", cls="fs-skip"),
             _nav(lang, current), Main(*content, id="main-content", tabindex="-1"), _footer(lang)),
        lang=lang,
    )



def _pricing_section(lang: str):
    T = lambda key: i18n.t(key, lang)
    return Section(Div(
        Div(fs_eyebrow(T("pricing.kicker")), H2(T("pricing.title")),
            P(T("pricing.lede")), cls="lh-head center"),
        Div(*[Article(
            fs_eyebrow(T(f"pricing.{kind}_eyebrow")), H3(T(f"pricing.{kind}_title")),
            P(T(f"pricing.{kind}_price"), cls="amt"), P(T(f"pricing.{kind}_body")),
            cls="lh-price feature" if kind == "hosted" else "lh-price",
        ) for kind in ("byoc", "hosted")], cls="lh-prices"),
        cls="fs-wrap"), id="pricing", cls="lh-sec")


def _dashboard_mock(lang: str):
    T = lambda key: i18n.t(key, lang)
    M = lambda key: T(f"landing.mock_{key}")
    groups = [
        ("bureau", ("overview",)),
        ("documents", ("invoices", "bills", "contacts")),
        ("money", ("banking",)),
        ("accounting", ("accounting", "tax")),
        ("payroll", ("payroll",)),
        ("settings", ("integrations",)),
    ]
    return Div(Div(
        Div(Span(cls="lh-dot"), Span(cls="lh-dot"), Span(cls="lh-dot"),
            Span(M("browser"), cls="lh-mock-url"), cls="lh-mock-bar"),
        Div(
            Div(Div(Span(cls="lh-app-dot"), Span(FASTPRODUCT.name, cls="lh-app-brand-fast"),
                    cls="lh-app-brand"),
                Span(M("sample"), cls="lh-app-meta"), cls="lh-appbar"),
            Div(*[Div(Span(T(f"nav.{group}"), cls="lh-side-label"),
                      *[Span(T(f"nav.{item}") if item != "accounting" else M("ledger"),
                             cls="lh-side-item on" if item == "overview" else "lh-side-item")
                        for item in items], cls="lh-side-group")
                  for group, items in groups], cls="lh-side"),
            Div(
                Div(M("title"), Span(M("subtitle"), cls="lh-hello-sub"), cls="lh-hello"),
                Div(*[Div(Small(M(key)), B(M(f"{key}_value")), cls="lh-kpi")
                      for key in ("open_invoices", "bank_lines", "vat_due")], cls="lh-kpis"),
                Div(
                    Div(Div(M("recent_invoices"), cls="lh-panel-title"),
                        *[Div(Div(B(M(f"invoice{n}")), Small(M(f"invoice{n}_amount")), cls="lh-row-txt"),
                              Span(M(status), cls="lh-tag"), cls="lh-row")
                          for n, status in ((1, "paid"), (2, "sent"), (3, "draft"))], cls="lh-panel"),
                    Div(Div(M("reconciliation"), cls="lh-panel-title"),
                        *[Div(Span(M(key)), I(style=f"width:{width}%"), B(M(f"{key}_value")), cls="lh-bar")
                          for key, width in (("matched", 90), ("review", 36), ("unmatched", 18))],
                        cls="lh-panel"),
                    cls="lh-panels"), cls="lh-main"),
            cls="lh-mock-body"),
        cls="lh-mock", inert=True, aria_hidden="true"),
        *[Div(Small(T(f"landing.float_{kind}")), Strong(M(value)), Span(M(detail)),
              cls=f"lh-glass lh-glass-{kind}", inert=True, aria_hidden="true")
          for kind, value, detail in (("bank", "invoice1_amount", "sample"),
                                      ("invoice", "paid", "invoice1"),
                                      ("tax", "vat_due_value", "vat_due"))],
        cls="lh-mock-wrap")


def landing_page(lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    suite_products = ("fastmail", "fastoffice", "fastdrive", "fastmeet", "fasthr", "fastbooks")

    def actions(variant="primary"):
        return Div(fs_button(T("landing.hero_cta"), "/login", variant, "lg"),
                   fs_button(T("landing.view_source"), FASTPRODUCT.github_url, "ghost", "lg"),
                   cls="lh-actions")

    return public_page(
        Section(
            Div(fs_eyebrow(T("landing.hero_eyebrow"), on_ink=True),
                H1(T("landing.hero_h1"), " ", T("landing.hero_highlight_prefix"), " ", Span(T("landing.hero_highlight"), cls="lh-hi")),
                P(T("landing.hero_sub"), cls="lh-sub"), actions(),
                P(T("landing.hero_trust"), cls="lh-trust"), cls="lh-hero-inner fs-wrap"),
            id="hero", cls="lh-hero"),
        Section(_dashboard_mock(lang), id="dashboard", cls="lh-demo", aria_hidden="true", inert=True),
        Section(Div(
            Div(H2(T("landing.audience_title")), P(T("landing.audience_body")), cls="lh-head"),
            Div(
                Article(H3(T("landing.audience_bureau_title")), P(T("landing.audience_bureau_body")),
                        fs_button(T("landing.audience_bureau_cta"), "#bureaus", "outline"),
                        cls="lh-audience"),
                Article(H3(T("landing.audience_business_title")), P(T("landing.audience_business_body")),
                        fs_button(T("landing.audience_business_cta"), "#why", "outline"),
                        cls="lh-audience"),
                cls="lh-audience-grid"),
            cls="fs-wrap"), id="audiences", cls="lh-sec"),
        Section(Div(
            Div(H2(T("landing.suite_title")), P(T("landing.suite_label")), cls="lh-suite-head"),
            Div(*[Article(
                H3(T(f"landing.suite_{key}_name")),
                P(T(f"landing.suite_{key}_body")),
                A(T(f"landing.suite_{key}_cta"), href=FASTPRODUCT.suite_url),
                cls="lh-suite-product") for key in suite_products], cls="lh-suite-products"),
            cls="fs-wrap"), id="suite", cls="lh-suite"),
        Section(Div(
            Div(Div(H2(T("landing.small_business_title")), cls="lh-head"),
                P(T("landing.small_business_body")), cls="lh-features-head"),
            Div(*[Article(
                I(f"{index:02d}", aria_hidden="true"),
                Span(T(f"landing.{key}_label"), cls="lh-feat-label"),
                H3(T(f"landing.{key}_title")), P(T(f"landing.{key}_body")), cls="lh-feat")
                for index, key in enumerate(("invoice", "reconcile", "review"), 1)],
                cls="lh-feats"), cls="fs-wrap"), id="why", cls="lh-sec"),
        Section(Div(
            Div(H2(T("landing.process_title")), P(T("landing.process_body")), cls="lh-head"),
            Ol(*[Li(Span(f"{n:02d}", cls="lh-step-number", aria_hidden="true"),
                    H3(T(f"landing.step{n}_title")), P(T(f"landing.step{n}_body")))
                 for n in range(1, 5)], cls="lh-steps"),
            cls="fs-wrap"), id="process", cls="lh-sec lh-process"),
        Section(Div(
            Div(H2(T("landing.comparison_title")), cls="lh-head"),
            Div(*[Article(H3(T(f"landing.{way}_title")),
                          Ul(*[Li(Span(fs_icon(symbol), cls="lh-mark"), T(f"landing.{way}{n}"))
                               for n in range(1, 5)]), cls=f"lh-compare-panel {way}")
                  for way, symbol in (("old", "close"), ("new", "check"))], cls="lh-comparison"),
            cls="fs-wrap"), id="comparison", cls="lh-sec"),
        Section(Div(Div(
            Div(H2(T("bureau.title")), P(T("bureau.body")),
                fs_button(T("bureau.cta"), "/login"), cls="lh-head"),
            Div(*[Article(B(T(f"bureau.{key}_title")), P(T(f"bureau.{key}_body")), cls="lh-stat-item")
                  for key in ("clients", "payroll", "matches", "tax")], cls="lh-stat-list"),
            cls="lh-stat"), cls="fs-wrap"), id="bureaus", cls="lh-sec lh-alt"),
        _pricing_section(lang),
        Section(Div(Dl(
            Div(Dt(T("landing.stats_languages")), Dd(T("landing.stats_languages_value"))),
            Div(Dt(T("landing.stats_markets")), Dd(T("landing.stats_markets_value"))),
            Div(Dt(T("pricing.byoc_eyebrow")), Dd(T("pricing.byoc_price"))),
            Div(Dt(T("pricing.hosted_eyebrow")), Dd(T("pricing.hosted_price"))),
        ), cls="fs-wrap"), id="product-facts", cls="lh-facts", aria_label=T("landing.stats_label")),
        Section(Div(
            Div(fs_eyebrow(T("landing.faq_eyebrow")), H2(T("landing.faq_title")), cls="lh-head"),
            Div(*[Details(Summary(T(f"landing.faq{n}_q")), P(T(f"landing.faq{n}_a")), cls="lh-faq", name="faq")
                  for n in range(1, 6)], cls="lh-faqs"),
            cls="fs-wrap"), id="faq", cls="lh-sec lh-alt"),
        Section(Div(Div(H2(T("landing.cta_title")), P(T("landing.cta_body")), actions(),
                        cls="lh-ctaband"), cls="fs-wrap"), id="get-started", cls="lh-close"),
        title=T("landing.title"), current="/", lang=lang,
    )


def _integration_availability(item: integrations.Integration) -> str:
    if item.key in {"file_import", "fasthr"}:
        return "available"
    if item.key in {"quickbooks", "xero", "merit", "smartaccounts", "bamboohr", "personio"}:
        return "review_required"
    if item.key in {"hmrc", "emta"}:
        return "pilot"
    return "planned"


def _integration_card(item: integrations.Integration, lang: str):
    T = lambda key: i18n.t(key, lang)
    copy = i18n.integration_copy(lang, item.key)
    return Article(
        Div(
            Div(Img(src=item.logo, alt=copy.get("logo_alt", item.logo_alt), loading="lazy", cls="integration-logo"), cls="integration-logo-wrap"),
            Div(Span(T(f"availability.{_integration_availability(item)}"), cls="availability"),
                Span(" · ".join(item.markets), cls="markets"), cls="provider-meta"),
            cls="integration-head",
        ),
        H2(copy.get("name", item.name)),
        Span(copy.get("category", item.category), cls="category"),
        P(copy.get("description", item.description)),
        Div(*[Span(capability, cls="capability") for capability in copy.get("capabilities", item.capabilities)], cls="capabilities"),
        Div(
            Div(Span(T("integrations.direction")), Strong(copy.get("direction", item.direction))),
            Div(Span(T("integrations.ownership")), Strong(copy.get("ownership", item.ownership))),
            cls="ownership",
        ),
        A(T("integrations.docs"), fs_icon("external"), href=item.docs_url, target="_blank", rel="noopener noreferrer", cls="docs"),
        id=item.key,
        cls="integration",
    )


def integrations_page(lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    return public_page(
        Section(
            Span(T("integrations.kicker"), cls="kicker"),
            H1(T("integrations.headline")),
            P(T("integrations.lede"), cls="lede"),
            Div(
                *[Span(T(f"availability.{status}"), cls="chip")
                  for status in ("available", "review_required", "pilot", "planned")],
                cls="summary",
            ),
            cls="page-hero",
        ),
        Section(Div(*[_integration_card(item, lang) for item in integrations.CATALOGUE], cls="integration-grid"), cls="catalogue"),
        Section(Div(Strong(T("integrations.review_gate")), T("integrations.review_notice")), cls="notice"),
        title=T("integrations.title"),
        current="/integrations",
        lang=lang,
    )


CONTACT_EMAIL = "info@predictivelabs.ai"


def _public_page_copy(lang: str, page: str) -> dict:
    fallback = i18n.catalog(i18n.DEFAULT_LANG).get("public_pages", {}).get(page, {})
    translated = i18n.catalog(lang).get("public_pages", {}).get(page, {})
    return translated if isinstance(translated, dict) else fallback


def _contact_link(section: dict, rank: int):
    subject = quote(section["email_subject"], safe="")
    classes = ("fs-btn fs-btn-ink" if rank == 0 else
               "fs-btn fs-btn-outline" if rank == 1 else "trust-text-link")
    return A(section["action"], href=f"mailto:{CONTACT_EMAIL}?subject={subject}", cls=classes)


def _information_page(page: str, lang: str):
    copy = _public_page_copy(lang, page)
    sections = []
    action_count = 0
    for section in copy["sections"]:
        action = None
        if section.get("email_subject"):
            action = _contact_link(section, action_count)
            action_count += 1
        sections.append(Article(
            H2(section["title"]),
            P(section["body"]),
            action,
            cls="trust-section",
        ))
    return public_page(
        Section(Div(H1(copy["title"]), P(copy["lede"], cls="lede"),
                    Span(copy["note"], cls="trust-note"), cls="trust-hero-inner fs-wrap"),
                cls="trust-hero"),
        Section(Div(*sections, cls="trust-layout fs-wrap"), cls="trust-content"),
        title=copy["title"], current=f"/{page}", lang=lang,
    )


def security_page(lang: str = i18n.DEFAULT_LANG):
    return _information_page("security", lang)


def privacy_page(lang: str = i18n.DEFAULT_LANG):
    return _information_page("privacy", lang)


def about_page(lang: str = i18n.DEFAULT_LANG):
    return _information_page("about", lang)


def contact_page(lang: str = i18n.DEFAULT_LANG):
    return _information_page("contact", lang)


def terms_page(lang: str = i18n.DEFAULT_LANG):
    return _information_page("terms", lang)


def roadmap_page(lang: str = i18n.DEFAULT_LANG):
    copy = _public_page_copy(lang, "roadmap")
    stages = []
    for stage in copy["stages"]:
        items = []
        for item in stage["items"]:
            heading = item["title"]
            if item.get("date"):
                heading = f"{heading} · {item['date']}"
            items.append(Article(H3(heading), P(item["body"]),
                                 Span(item["market"], cls="market-tag"), cls="roadmap-item"))
        stages.append(Section(H2(stage["title"]), P(stage["intro"], cls="lede"),
                              Div(*items, cls="roadmap-items"), cls="release-group"))
    return public_page(
        Section(Div(H1(copy["title"]), P(copy["lede"], cls="lede"),
                    Span(copy["note"], cls="trust-note"), cls="trust-hero-inner fs-wrap"),
                cls="trust-hero"),
        Section(Div(*stages,
                    P(copy["source_intro"], " ",
                      A(copy["source_link"], href="/changelog"), cls="trust-source"),
                    cls="fs-wrap"), cls="trust-content"),
        title=copy["title"], current="/roadmap", lang=lang,
    )


def changelog_page(lang: str = i18n.DEFAULT_LANG):
    copy = _public_page_copy(lang, "changelog")
    releases = []
    for release in copy["releases"]:
        releases.append(Article(
            Div(H2(release["title"]), Time(release["date"], datetime=release["date"], cls="release-date"), cls="release-head"),
            P(release["body"]), cls="release-group",
        ))
    return public_page(
        Section(Div(H1(copy["title"]), P(copy["lede"], cls="lede"),
                    Span(copy["note"], cls="trust-note"), cls="trust-hero-inner fs-wrap"),
                cls="trust-hero"),
        Section(Div(*releases,
                    P(copy["source_intro"], " ",
                      A(copy["source_link"], href=f"{FASTPRODUCT.github_url}/blob/main/docs/change_log.md"),
                      cls="trust-source"), cls="fs-wrap"), cls="trust-content"),
        title=copy["title"], current="/changelog", lang=lang,
    )


LOGIN_TABS = ("signin", "register", "forgot")


def _auth_field(field_id, name, label, **attrs):
    return Div(Label(label, **{"for": field_id}), Input(id=field_id, name=name, cls="auth-field", **attrs),
               cls="auth-field-wrap")


def _auth_messages(error: str, notice: str):
    return (Div(error, cls="error", role="alert") if error else None,
            Div(notice, cls="auth-notice", role="status") if notice else None)


def login_page(error: str = "", lang: str = i18n.DEFAULT_LANG, *, tab: str = "signin", notice: str = "",
               csrf: str = "", next_path: str = "", email: str = ""):
    T = lambda key: i18n.t(key, lang)
    A_ = lambda key: i18n.t(f"auth.{key}", lang)
    tab = tab if tab in LOGIN_TABS else "signin"
    message = error.strip()[:240]
    hidden = [Input(type="hidden", name="csrf_token", value=csrf)]
    if next_path:
        hidden.append(Input(type="hidden", name="next", value=next_path))
    tab_href = lambda key: "/login" + (f"?tab={key}" if key != "signin" else "") + (
        ("&" if key != "signin" else "?") + "next=" + quote(next_path, safe="") if next_path else "")
    tabs = Nav(*[A(A_(f"tab_{key}"), href=tab_href(key), cls="auth-tab",
                   aria_current="page" if (tab == key or (key == "signin" and tab == "forgot")) else "false")
                 for key in ("signin", "register")], cls="auth-tabs", aria_label=A_("tabs_label"))
    if tab == "register":
        form = Form(*hidden,
                    _auth_field("auth-register-name", "name", A_("name"), autocomplete="name", required=True, maxlength="120"),
                    _auth_field("auth-register-email", "email", A_("email"), type="email", autocomplete="email",
                                required=True, value=email, maxlength="254"),
                    _auth_field("auth-register-password", "password", A_("password_choose"), type="password",
                                autocomplete="new-password", required=True, minlength="10", maxlength="1024"),
                    Button(A_("submit_register"), type="submit", cls="fs-btn fs-btn-primary auth-submit"),
                    method="post", action="/auth/local/register", cls="auth-form", id="auth-register-form")
        extra = P(A_("register_help"), cls="auth-help")
    elif tab == "forgot":
        form = Form(*hidden,
                    P(A_("forgot_intro"), cls="auth-help"),
                    _auth_field("auth-forgot-email", "email", A_("email"), type="email", autocomplete="email",
                                required=True, value=email, maxlength="254"),
                    Button(A_("submit_forgot"), type="submit", cls="fs-btn fs-btn-primary auth-submit"),
                    A(A_("back_to_signin"), href=tab_href("signin"), cls="auth-link"),
                    method="post", action="/auth/local/forgot", cls="auth-form", id="auth-forgot-form")
        extra = None
    else:
        form = Form(*hidden,
                    _auth_field("auth-login-email", "email", A_("email"), type="email", autocomplete="email",
                                required=True, value=email, maxlength="254"),
                    _auth_field("auth-login-password", "password", A_("password"), type="password",
                                autocomplete="current-password", required=True, maxlength="1024"),
                    A(A_("forgot_link"), href=tab_href("forgot"), cls="auth-link auth-forgot"),
                    Button(A_("submit_signin"), type="submit", cls="fs-btn fs-btn-primary auth-submit"),
                    method="post", action="/auth/local/login", cls="auth-form", id="auth-login-form")
        extra = None
    return public_page(
        Section(
            Div(
                Span(T("login.kicker"), cls="kicker"),
                H1(T("login.headline")),
                P(T("login.body")),
                *_auth_messages(message, notice),
                A(T("login.continue_google") if google_auth.enabled() else T("login.not_configured"),
                  href="/auth/google" + ("?next=" + quote(next_path, safe="") if next_path else ""),
                  cls="fs-btn fs-btn-outline google"),
                P(T("login.configuration_hint")) if not google_auth.enabled() else None,
                Div(A_("or"), cls="auth-divider"),
                tabs,
                form,
                extra,
                cls="auth-card", data_auth_tab=tab,
            ),
            cls="auth-wrap",
        ),
        title=T("login.title"),
        current="/login",
        lang=lang,
    )


def mfa_page(account: dict | None = None, lang: str = "en", *, csrf: str = "",
             pending: dict | None = None, secret: str = "", recovery: list[str] | None = None,
             error: str = "", notice: str = ""):
    from web.totp import uri
    T = lambda key: i18n.t(f"auth.{key}", lang)

    def form(action, *, password=False, factor=False, regenerate=False):
        fields = [Input(type="hidden", name="csrf_token", value=csrf)]
        if pending:
            fields.append(Input(type="hidden", name="token", value=pending["token"]))
        if regenerate:
            fields.append(Input(type="hidden", name="regenerate", value="1"))
        if password:
            fields.append(_auth_field(f"mfa-{action}-password", "password", T("password"), type="password",
                                      autocomplete="current-password", required=True, maxlength="1024"))
        if factor:
            fields.append(_auth_field(f"mfa-{action}-code", "code", T("mfa_code"), autocomplete="one-time-code",
                                      required=True, maxlength="128"))
        return Form(*fields, Button(T("mfa_" + ("restart" if regenerate else action)), type="submit",
                                    cls="fs-btn fs-btn-primary auth-submit"),
                    method="post", action=f"/auth/mfa/{action}", cls="auth-form")

    content = []
    if pending:
        content = [P(T("mfa_challenge_intro")), form("challenge", factor=True)]
    elif recovery is not None:
        content = [H2(T("mfa_recovery_title")), P(T("mfa_recovery_help")),
                   Ul(*[Li(Code(value), cls="mfa-recovery-code") for value in recovery]),
                   A(T("mfa_acknowledge"), href="/mfa", cls="auth-link")]
    elif account:
        content.append(P(T("mfa_enabled" if account["totp_enabled"] else "mfa_disabled")))
        if account["totp_enabled"]:
            content += [form("disable", password=True, factor=True), form("codes", password=True, factor=True)]
        elif secret:
            content += [P(T("mfa_setup_help")),
                        _auth_field("mfa-secret", "secret", T("mfa_secret"), value=secret, readonly=True),
                        _auth_field("mfa-uri", "uri", T("mfa_uri"), value=uri(secret, account["email"]), readonly=True),
                        form("activate", factor=True), form("enroll", password=True, regenerate=True)]
        else:
            content += [P(T("mfa_enroll_help")), form("enroll", password=True, regenerate=bool(account["totp_secret"]))]
        content.append(A(T("mfa_back"), href="/app", cls="auth-link"))
    return public_page(Section(Div(H1(T("mfa_title")), *_auth_messages(error, notice), *content,
                                   cls="auth-card"), cls="auth-wrap"),
                       title=T("mfa_title"), current="/mfa", lang=lang)


def password_token_page(purpose: str, token: str, lang: str = i18n.DEFAULT_LANG, *, csrf: str = "",
                        error: str = ""):
    """New-password form (reset) or password confirmation (email verification)."""
    A_ = lambda key: i18n.t(f"auth.{key}", lang)
    purpose = "verify" if purpose == "verify" else "reset"
    field = _auth_field(f"auth-{purpose}-password", "password",
                        A_("password_new") if purpose == "reset" else A_("password"), type="password",
                        autocomplete="new-password" if purpose == "reset" else "current-password",
                        required=True, maxlength="1024", **({"minlength": "10"} if purpose == "reset" else {}))
    return public_page(
        Section(
            Div(
                Span(i18n.t("login.kicker", lang), cls="kicker"),
                H1(A_(f"{purpose}_title")),
                P(A_(f"{purpose}_intro")),
                *_auth_messages(error, ""),
                Form(Input(type="hidden", name="csrf_token", value=csrf),
                     Input(type="hidden", name="token", value=token),
                     field,
                     Button(A_(f"submit_{purpose}"), type="submit", cls="fs-btn fs-btn-primary auth-submit"),
                     A(A_("back_to_signin"), href="/login", cls="auth-link"),
                     method="post", action=f"/auth/local/{purpose}", cls="auth-form", id=f"auth-{purpose}-form"),
                cls="auth-card", data_auth_tab=purpose,
            ),
            cls="auth-wrap",
        ),
        title=A_(f"{purpose}_title"),
        current="/login",
        lang=lang,
    )


def workspace_page(user: dict, lang: str = "en"):
    T = lambda key: i18n.t(key, lang)
    display_name = user.get("name") or user.get("email") or ""
    groups = [
        ("bureau", [("overview", "overview")]),
        ("documents", [("invoices", "invoices"), ("quotes", "quotes"), ("bills", "bills"), ("periodised", "periodised"), ("contacts", "contacts")]),
        ("automation", [("recurring", "recurring")]),
        ("money", [("banking", "banking")]),
        ("accounting", [("accounting", "accounting"), ("cash-flow", "cash_flow"), ("fixed-assets", "fixed_assets"), ("periods", "periods"), ("tax", "tax")]),
        ("payroll", [("payroll", "payroll")]),
        ("settings", [("integrations", "integrations"), ("imports", "data_import"), ("payment-methods", "payment_methods"), ("payment-types", "payment_types"), ("reminder-rules", "reminder_rules"), ("exchange-rates", "fx_rates"), ("objects", "objects"), ("groups", "groups"), ("documents", "document_settings"), ("maintenance", "maintenance")]),
    ]
    # Escape script delimiters even when catalogue copy contains HTML punctuation.
    dictionary = {**i18n.catalog("en"), **i18n.catalog(lang)}
    dictionary["workspace"] = {**i18n.catalog("en").get("workspace", {}), **i18n.catalog(lang).get("workspace", {})}
    payload = json.dumps(dictionary, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (
        Title(f"{T('nav.workspace')} · FastAccounts"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="theme-color", content="#150a2c"),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Link(rel="apple-touch-icon", href="/static/brand/apple-touch-icon.png"),
        *FONT_LINKS,
        Link(rel="stylesheet", href=asset_url("app.css")),
        Div(
            Aside(
                A(Img(src="/static/brand/fastaccounts-mark.svg", alt="", width=32, height=32, cls="app-mark"), Span("FastAccounts"), href="/app", cls="app-brand"),
                A(version.label(), href="/healthz", title=version.detail(), cls="app-version", data_testid="app-version"),
                Div(
                    Button(T("actions.create_organisation"), id="org-trigger", cls="org-trigger", type="button", aria_haspopup="menu", aria_expanded="false", aria_controls="org-menu"),
                    Div(id="org-menu", cls="org-menu", role="menu", hidden=True),
                    cls="org-switcher",
                ),
                Nav(*[
                    Div(Span(T(f"nav.{group}"), cls="nav-group"), *[
                        A(T(f"nav.{label}"), href=f"#{view}", data_view=view, cls="app-nav")
                        for view, label in items
                    ]) for group, items in groups if items
                ], cls="app-nav-list", aria_label=T("nav.workspace")),
                Div(
                    Div(
                        A(T("nav.public_site"), href="/", cls="app-side-link", data_icon="external"),
                        A(T("workspace.Two-factor authentication"), href="/mfa", cls="app-side-link", data_icon="shield"),
                        cls="app-side-actions",
                    ),
                    Div(Span(display_name[:1].upper(), cls="user-avatar"), Div(Strong(display_name), A(T("nav.sign_out"), href="/logout")), cls="user-card"),
                    cls="app-side-links",
                ), cls="app-sidebar",
            ),
            Div(
                Header(
                    Div(Button(fs_icon("menu", "icon"), id="menu-toggle", aria_label=T("nav.open_navigation"), cls="menu-toggle"), Span(T("nav.workspace"), cls="workspace-label"), Strong(id="current-org")),
                    Div(*[A(info["native"], href=f"/set-lang/{code}?next=/app", lang=code, aria_current="true" if code == lang else "false") for code, info in i18n.LANGUAGES.items() if code in ("en", "et")], cls="workspace-languages", aria_label=T("language.choose")),
                    cls="app-topbar",
                ),
                Main(Div(Div(cls="skeleton rows-skeleton"), id="app-content", aria_live="polite"), cls="app-main"),
                cls="app-body",
            ),
            id="workspace-app", data_user_email=user.get("email", ""), data_lang=lang, lang=lang, cls="app-shell",
        ),
        Div(id="toasts", cls="toasts", aria_live="polite"),
        Script(NotStr(f"window.FASTACCOUNTS_I18N = {payload};")),
        Script(src=asset_url("app.js")),
    )
