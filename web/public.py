"""Public FastAccounts landing, sign-in, and integration catalogue pages."""
from __future__ import annotations

from urllib.parse import quote

from fasthtml.common import *

import integrations
import version
from . import google_auth, i18n


ACCENT = "#087f5b"
TINT = "#ecfdf5"

PUBLIC_CSS = """
:root{--accent:#087f5b;--accent-dark:#066349;--tint:#ecfdf5;--ink:#10231d;--muted:#607069;--line:#dfe8e4;--soft:#f7faf8}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:inherit}.nav{min-height:68px;max-width:1180px;margin:auto;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-weight:800}.mark{width:32px;height:32px;border-radius:10px;background:var(--accent);display:grid;place-items:center;color:white;font-size:17px}.brand em{color:var(--accent);font-style:normal}
.nav-links,.nav-actions{display:flex;align-items:center;gap:18px}.nav-link{font-size:14px;text-decoration:none;color:var(--muted);font-weight:650}.nav-link:hover{color:var(--accent)}
.language-picker{position:relative}.language-trigger{width:34px;height:34px;padding:0;border:1px solid transparent;border-radius:9px;background:transparent;font-size:17px;cursor:pointer}.language-trigger:hover,.language-trigger:focus{border-color:var(--line);outline:2px solid transparent;box-shadow:0 0 0 3px rgba(8,127,91,.15)}
.language-menu{display:none;position:absolute;right:0;top:calc(100% + 8px);z-index:20;min-width:148px;padding:6px 0;border:1px solid var(--line);border-radius:12px;background:#fff;box-shadow:0 18px 50px rgba(16,35,29,.16)}.language-menu.open{display:flex;flex-direction:column}.language-option{display:flex;align-items:center;gap:9px;padding:8px 12px;text-decoration:none;color:var(--muted);font-size:13px;white-space:nowrap}.language-option:hover,.language-option:focus,.language-option.active{background:var(--tint);color:var(--ink);outline:none}.language-flag{font-size:16px}
.button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;border-radius:999px;padding:10px 18px;text-decoration:none;font-size:14px;font-weight:750;border:1px solid var(--line);background:#fff}.button.primary{background:var(--accent);border-color:var(--accent);color:#fff}.button.primary:hover{background:var(--accent-dark)}
.hero{max-width:1180px;margin:auto;padding:104px 24px 86px}.kicker{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}.hero h1,.page-hero h1{font-size:clamp(44px,7vw,78px);line-height:1.02;letter-spacing:-.055em;max-width:940px;margin:20px 0}.lede{font-size:20px;line-height:1.65;color:var(--muted);max-width:760px}.hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:30px}
.band{background:var(--tint);border-block:1px solid #d5efe4}.feature-grid{max-width:1180px;margin:auto;padding:66px 24px;display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.feature{background:rgba(255,255,255,.86);border:1px solid #d5e9df;border-radius:20px;padding:26px}.feature strong{font-size:12px;color:var(--accent)}.feature h2{font-size:21px;margin:22px 0 9px}.feature p{color:var(--muted);line-height:1.6;margin:0}
.page-hero{max-width:1180px;margin:auto;padding:76px 24px 42px}.page-hero .lede{font-size:18px}.summary{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.chip{border:1px solid var(--line);border-radius:999px;padding:8px 13px;font-size:12px;font-weight:700;color:var(--muted)}
.catalogue{max-width:1180px;margin:auto;padding:14px 24px 74px}.integration-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.integration{border:1px solid var(--line);border-radius:22px;padding:24px;background:#fff;display:flex;flex-direction:column;min-height:350px}.integration-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.integration-logo-wrap{height:58px;min-width:140px;display:flex;align-items:center}.integration-logo{display:block;max-width:142px;max-height:50px;object-fit:contain}.provider-meta{text-align:right}.markets{display:block;margin-top:8px;color:var(--muted);font-size:11px;font-weight:750}.integration h2{font-size:23px;margin:24px 0 4px}.category{font-size:12px;color:var(--accent);font-weight:750}.integration>p{color:var(--muted);line-height:1.6}.capabilities{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 18px}.capability{background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:6px 9px;font-size:11px;color:var(--muted)}.ownership{border-top:1px solid var(--line);padding-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:14px;font-size:12px}.ownership span{display:block;color:var(--muted);margin-bottom:3px}.ownership strong{font-size:13px}.docs{color:var(--accent);text-decoration:none;font-size:13px;font-weight:750;margin-top:auto;padding-top:20px}
.notice{max-width:1180px;margin:0 auto 70px;padding:0 24px}.notice>div{border:1px solid #d5e9df;background:var(--tint);border-radius:18px;padding:22px;color:var(--muted);line-height:1.6}.notice strong{color:var(--ink)}
.auth-wrap{min-height:calc(100vh - 150px);display:grid;place-items:center;padding:60px 24px}.auth-card{width:min(470px,100%);border:1px solid var(--line);border-radius:24px;padding:34px;box-shadow:0 22px 70px rgba(16,35,29,.08)}.auth-card h1{font-size:32px;letter-spacing:-.035em;margin:8px 0}.auth-card p{color:var(--muted);line-height:1.6}.google{width:100%;margin-top:18px}.error{border-radius:12px;background:#fff1f0;color:#a61b1b;padding:12px 14px;font-size:13px}.workspace{max-width:900px;margin:auto;padding:80px 24px}.workspace h1{font-size:44px;letter-spacing:-.04em}.workspace p{color:var(--muted);line-height:1.65}
.footer{max-width:1180px;margin:auto;padding:30px 24px 46px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;color:var(--muted);font-size:13px}.footer-links{display:flex;gap:16px;flex-wrap:wrap}.footer a{color:var(--accent);text-decoration:none}
@media(max-width:820px){.feature-grid{grid-template-columns:1fr}.integration-grid{grid-template-columns:1fr}.nav-links{display:none}.hero{padding-top:72px}.footer{flex-direction:column}}
@media(max-width:500px){.nav{padding-inline:16px}.button{padding:9px 13px}.brand span:last-child{font-size:15px}.integration{padding:19px}.integration-head{align-items:center}.integration-logo-wrap{min-width:110px}.integration-logo{max-width:110px}.ownership{grid-template-columns:1fr}.hero,.page-hero,.catalogue{padding-inline:18px}}
"""


def _language_switcher(lang: str, current: str):
    selected = i18n.LANGUAGES.get(lang, i18n.LANGUAGES[i18n.DEFAULT_LANG])
    return Div(
        Button(
            selected["flag"],
            type="button",
            id="language-menu-button",
            aria_label=i18n.t("language.choose", lang),
            aria_haspopup="true",
            aria_expanded="false",
            onclick="toggleLanguageMenu(event)",
            cls="language-trigger",
        ),
        Div(
            *[
                A(
                    Span(info["flag"], cls="language-flag"),
                    Span(info["native"]),
                    href=f"/set-lang/{code}?next={quote(current, safe='/')}",
                    lang=code,
                    role="menuitem",
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
    return Nav(
        A(Span("F", cls="mark"), Span("Fast", Em("Accounts")), href="/", cls="brand"),
        Div(
            A(T("nav.why"), href="/#why", cls="nav-link"),
            A(T("nav.integrations"), href="/integrations", cls="nav-link"),
            A(T("nav.roadmap"), href="https://github.com/predictivelabsai/FastAccounts", cls="nav-link"),
            cls="nav-links",
        ),
        Div(
            _language_switcher(lang, current),
            A(T("nav.sign_in"), href="/login", cls="button"),
            cls="nav-actions",
        ),
        cls="nav",
    )


def _footer(lang: str):
    T = lambda key: i18n.t(key, lang)
    return Footer(
        Span(T("footer.tagline")),
        Div(
            A(T("footer.integrations"), href="/integrations"),
            A(T("footer.source"), href="https://github.com/predictivelabsai/FastAccounts"),
            A(version.label(), href="/healthz", title=version.detail()),
            cls="footer-links",
        ),
        cls="footer",
    )


def public_page(*content, title: str, current: str, lang: str):
    return Html(
        Head(
            Title(f"{title} · FastAccounts"),
            Meta(charset="utf-8"),
            Meta(name="viewport", content="width=device-width, initial-scale=1"),
            Meta(name="description", content=i18n.t("meta.description", lang)),
            Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
            Style(PUBLIC_CSS),
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
                        closeLanguageMenu();
                        const button = document.getElementById('language-menu-button');
                        if (button) button.focus();
                    }
                });
            """)),
        ),
        Body(_nav(lang, current), Main(*content), _footer(lang)),
        lang=lang,
    )


def landing_page(lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    return public_page(
        Section(
            Span(T("landing.kicker"), cls="kicker"),
            H1(T("landing.headline")),
            P(T("landing.lede"), cls="lede"),
            Div(
                A(T("landing.explore_integrations"), href="/integrations", cls="button primary"),
                A(T("landing.view_source"), href="https://github.com/predictivelabsai/FastAccounts", cls="button"),
                cls="hero-actions",
            ),
            cls="hero",
        ),
        Section(
            Div(
                Div(Strong(T("landing.invoice_label")), H2(T("landing.invoice_title")), P(T("landing.invoice_body")), cls="feature"),
                Div(Strong(T("landing.reconcile_label")), H2(T("landing.reconcile_title")), P(T("landing.reconcile_body")), cls="feature"),
                Div(Strong(T("landing.review_label")), H2(T("landing.review_title")), P(T("landing.review_body")), cls="feature"),
                cls="feature-grid",
            ),
            id="why",
            cls="band",
        ),
        title=T("landing.title"),
        current="/",
        lang=lang,
    )


def _integration_card(item: integrations.Integration, lang: str):
    T = lambda key: i18n.t(key, lang)
    copy = i18n.integration_copy(lang, item.key)
    return Article(
        Div(
            Div(Img(src=item.logo, alt=copy.get("logo_alt", item.logo_alt), loading="lazy", cls="integration-logo"), cls="integration-logo-wrap"),
            Div(Span(" · ".join(item.markets), cls="markets"), cls="provider-meta"),
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
        A(T("integrations.docs"), href=item.docs_url, target="_blank", rel="noopener noreferrer", cls="docs"),
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
                Span(T("integrations.accounting_adapters"), cls="chip"),
                Span(T("integrations.filing_gates"), cls="chip"),
                Span(T("integrations.banking_candidate"), cls="chip"),
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


def login_page(error: str = "", lang: str = i18n.DEFAULT_LANG):
    T = lambda key: i18n.t(key, lang)
    message = error.strip()[:240]
    return public_page(
        Section(
            Div(
                Span(T("login.kicker"), cls="kicker"),
                H1(T("login.headline")),
                P(T("login.body")),
                Div(message, cls="error") if message else None,
                A(T("login.continue_google") if google_auth.enabled() else T("login.not_configured"), href="/auth/google", cls="button primary google"),
                P(T("login.configuration_hint")) if not google_auth.enabled() else None,
                cls="auth-card",
            ),
            cls="auth-wrap",
        ),
        title=T("login.title"),
        current="/login",
        lang=lang,
    )


def workspace_page(user: dict):
    display_name = user.get("name") or user.get("email")
    return (
        Title("Workspace · FastAccounts"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Link(rel="stylesheet", href="/static/app.css"),
        Div(
            Aside(
                A(Span("F", cls="app-mark"), Span("FastAccounts"), href="/app", cls="app-brand"),
                Nav(
                    A("Overview", href="#overview", data_view="overview", cls="app-nav active"),
                    A("Invoices", href="#invoices", data_view="invoices", cls="app-nav"),
                    A("Bills", href="#bills", data_view="bills", cls="app-nav"),
                    A("Banking", href="#banking", data_view="banking", cls="app-nav"),
                    A("Accounting", href="#accounting", data_view="accounting", cls="app-nav"),
                    A("Tax", href="#tax", data_view="tax", cls="app-nav"),
                    A("Integrations", href="#integrations", data_view="integrations", cls="app-nav"),
                    cls="app-nav-list",
                ),
                Div(A("Public site", href="/"), A("Sign out", href="/logout"), cls="app-side-links"),
                cls="app-sidebar",
            ),
            Div(
                Header(
                    Div(Button("☰", id="menu-toggle", aria_label="Open navigation", cls="menu-toggle"),
                        Div(Span("Workspace", cls="eyebrow"), Strong(display_name))),
                    Select(Option("Loading organisations…", value=""), id="organisation-select", aria_label="Organisation"),
                    cls="app-topbar",
                ),
                Main(
                    Div(Span("Loading your books…", cls="loading"), id="app-content"),
                    cls="app-main",
                ),
                cls="app-body",
            ),
            id="workspace-app",
            data_user_email=user.get("email", ""),
            cls="app-shell",
        ),
        Script(src="/static/app.js"),
    )
