"""Public FastAccounts landing, sign-in, and integration catalogue pages."""
from __future__ import annotations

from fasthtml.common import *

import integrations
import version
from . import google_auth


ACCENT = "#087f5b"
TINT = "#ecfdf5"

PUBLIC_CSS = """
:root{--accent:#087f5b;--accent-dark:#066349;--tint:#ecfdf5;--ink:#10231d;--muted:#607069;--line:#dfe8e4;--soft:#f7faf8;--warn:#9a6700}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#fff;color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:inherit}.nav{min-height:68px;max-width:1180px;margin:auto;padding:12px 24px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;font-weight:800}.mark{width:32px;height:32px;border-radius:10px;background:var(--accent);display:grid;place-items:center;color:white;font-size:17px}.brand em{color:var(--accent);font-style:normal}
.nav-links,.nav-actions{display:flex;align-items:center;gap:18px}.nav-link{font-size:14px;text-decoration:none;color:var(--muted);font-weight:650}.nav-link:hover{color:var(--accent)}
.button{display:inline-flex;align-items:center;justify-content:center;min-height:42px;border-radius:999px;padding:10px 18px;text-decoration:none;font-size:14px;font-weight:750;border:1px solid var(--line);background:#fff}.button.primary{background:var(--accent);border-color:var(--accent);color:#fff}.button.primary:hover{background:var(--accent-dark)}
.hero{max-width:1180px;margin:auto;padding:104px 24px 86px}.kicker{color:var(--accent);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}.hero h1,.page-hero h1{font-size:clamp(44px,7vw,78px);line-height:1.02;letter-spacing:-.055em;max-width:940px;margin:20px 0}.lede{font-size:20px;line-height:1.65;color:var(--muted);max-width:760px}.hero-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:30px}
.band{background:var(--tint);border-block:1px solid #d5efe4}.feature-grid{max-width:1180px;margin:auto;padding:66px 24px;display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.feature{background:rgba(255,255,255,.86);border:1px solid #d5e9df;border-radius:20px;padding:26px}.feature strong{font-size:12px;color:var(--accent)}.feature h2{font-size:21px;margin:22px 0 9px}.feature p{color:var(--muted);line-height:1.6;margin:0}
.page-hero{max-width:1180px;margin:auto;padding:76px 24px 42px}.page-hero .lede{font-size:18px}.summary{display:flex;gap:10px;flex-wrap:wrap;margin-top:24px}.chip{border:1px solid var(--line);border-radius:999px;padding:8px 13px;font-size:12px;font-weight:700;color:var(--muted)}
.catalogue{max-width:1180px;margin:auto;padding:14px 24px 74px}.integration-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.integration{border:1px solid var(--line);border-radius:22px;padding:24px;background:#fff;display:flex;flex-direction:column;min-height:350px}.integration-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}.integration-logo-wrap{height:58px;min-width:140px;display:flex;align-items:center}.integration-logo{display:block;max-width:142px;max-height:50px;object-fit:contain}.provider-meta{text-align:right}.status{display:inline-flex;border-radius:999px;padding:6px 9px;background:#fff8db;color:var(--warn);font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.08em}.markets{display:block;margin-top:8px;color:var(--muted);font-size:11px;font-weight:750}.integration h2{font-size:23px;margin:24px 0 4px}.category{font-size:12px;color:var(--accent);font-weight:750}.integration>p{color:var(--muted);line-height:1.6}.capabilities{display:flex;gap:7px;flex-wrap:wrap;margin:8px 0 18px}.capability{background:var(--soft);border:1px solid var(--line);border-radius:999px;padding:6px 9px;font-size:11px;color:var(--muted)}.ownership{border-top:1px solid var(--line);padding-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:14px;font-size:12px}.ownership span{display:block;color:var(--muted);margin-bottom:3px}.ownership strong{font-size:13px}.docs{color:var(--accent);text-decoration:none;font-size:13px;font-weight:750;margin-top:auto;padding-top:20px}
.notice{max-width:1180px;margin:0 auto 70px;padding:0 24px}.notice>div{border:1px solid #d5e9df;background:var(--tint);border-radius:18px;padding:22px;color:var(--muted);line-height:1.6}.notice strong{color:var(--ink)}
.auth-wrap{min-height:calc(100vh - 150px);display:grid;place-items:center;padding:60px 24px}.auth-card{width:min(470px,100%);border:1px solid var(--line);border-radius:24px;padding:34px;box-shadow:0 22px 70px rgba(16,35,29,.08)}.auth-card h1{font-size:32px;letter-spacing:-.035em;margin:8px 0}.auth-card p{color:var(--muted);line-height:1.6}.google{width:100%;margin-top:18px}.error{border-radius:12px;background:#fff1f0;color:#a61b1b;padding:12px 14px;font-size:13px}.workspace{max-width:900px;margin:auto;padding:80px 24px}.workspace h1{font-size:44px;letter-spacing:-.04em}.workspace p{color:var(--muted);line-height:1.65}
.footer{max-width:1180px;margin:auto;padding:30px 24px 46px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:20px;color:var(--muted);font-size:13px}.footer-links{display:flex;gap:16px;flex-wrap:wrap}.footer a{color:var(--accent);text-decoration:none}
@media(max-width:820px){.feature-grid{grid-template-columns:1fr}.integration-grid{grid-template-columns:1fr}.nav-links{display:none}.hero{padding-top:72px}.footer{flex-direction:column}}
@media(max-width:500px){.nav{padding-inline:16px}.button{padding:9px 13px}.brand span:last-child{font-size:15px}.integration{padding:19px}.integration-head{align-items:center}.integration-logo-wrap{min-width:110px}.integration-logo{max-width:110px}.ownership{grid-template-columns:1fr}.hero,.page-hero,.catalogue{padding-inline:18px}}
"""


def _nav():
    return Nav(
        A(Span("F", cls="mark"), Span("Fast", Em("Accounts")), href="/", cls="brand"),
        Div(
            A("Why FastAccounts", href="/#why", cls="nav-link"),
            A("Integrations", href="/integrations", cls="nav-link"),
            A("Roadmap", href="https://github.com/predictivelabsai/FastAccounts", cls="nav-link"),
            cls="nav-links",
        ),
        Div(A("Sign In", href="/login", cls="button"), cls="nav-actions"),
        cls="nav",
    )


def _footer():
    return Footer(
        Span("Open-source bookkeeping for the UK and Estonia."),
        Div(
            A("Integrations", href="/integrations"),
            A("Source", href="https://github.com/predictivelabsai/FastAccounts"),
            A(version.label(), href="/healthz", title=version.detail()),
            cls="footer-links",
        ),
        cls="footer",
    )


def public_page(*content, title: str):
    return (
        Title(f"{title} · FastAccounts"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="description", content="Open-source bookkeeping and accounting for UK and Estonian businesses."),
        Link(rel="icon", type="image/svg+xml", href="/static/favicon.svg"),
        Style(PUBLIC_CSS),
        _nav(),
        Main(*content),
        _footer(),
    )


def landing_page():
    return public_page(
        Section(
            Span("Books built for two markets", cls="kicker"),
            H1("Bookkeeping that stays clear, portable, and accountant-ready."),
            P("Create invoices, capture bills, reconcile cash, keep an immutable double-entry ledger, and prepare reviewed UK and Estonian VAT workpapers—without adopting a full ERP.", cls="lede"),
            Div(
                A("Explore integrations", href="/integrations", cls="button primary"),
                A("View the source", href="https://github.com/predictivelabsai/FastAccounts", cls="button"),
                cls="hero-actions",
            ),
            cls="hero",
        ),
        Section(
            Div(
                Div(Strong("01 · INVOICE"), H2("Sell and get paid"), P("Country-aware invoices, credit notes, payments, reminders, and a complete receivables trail."), cls="feature"),
                Div(Strong("02 · RECONCILE"), H2("Know where cash went"), P("Import statements, match with evidence and documents, and review ambiguity before anything posts."), cls="feature"),
                Div(Strong("03 · REVIEW"), H2("Hand over clean books"), P("VAT workpapers, ledgers, reports, evidence, audit history, and explicit filing-agent plans."), cls="feature"),
                cls="feature-grid",
            ),
            id="why",
            cls="band",
        ),
        title="Open bookkeeping",
    )


def _integration_card(item: integrations.Integration):
    return Article(
        Div(
            Div(Img(src=item.logo, alt=item.logo_alt, loading="lazy", cls="integration-logo"), cls="integration-logo-wrap"),
            Div(Span(item.status, cls="status"), Span(" · ".join(item.markets), cls="markets"), cls="provider-meta"),
            cls="integration-head",
        ),
        H2(item.name),
        Span(item.category, cls="category"),
        P(item.description),
        Div(*[Span(capability, cls="capability") for capability in item.capabilities], cls="capabilities"),
        Div(
            Div(Span("Direction"), Strong(item.direction)),
            Div(Span("Record ownership"), Strong(item.ownership)),
            cls="ownership",
        ),
        A("Read provider documentation ↗", href=item.docs_url, target="_blank", rel="noopener noreferrer", cls="docs"),
        id=item.key,
        cls="integration",
    )


def integrations_page():
    return public_page(
        Section(
            Span("Coexist by design", cls="kicker"),
            H1("Connect the tools your accountant already uses."),
            P("FastAccounts can exchange data through tested provider adapters while making direction, ownership, review, and conflicts visible. No provider below is connected by default, and tax submission remains gated.", cls="lede"),
            Div(
                Span("3 accounting adapters", cls="chip"),
                Span("2 filing gates", cls="chip"),
                Span("Read-only banking candidate", cls="chip"),
                cls="summary",
            ),
            cls="page-hero",
        ),
        Section(Div(*[_integration_card(item) for item in integrations.CATALOGUE], cls="integration-grid"), cls="catalogue"),
        Section(Div(Strong("Review gate: "), "Imports and exports produce reconciliation records. Direct tax submission stays disabled until provider approval, accountant UAT, and explicit finalisation controls are complete."), cls="notice"),
        title="Integrations",
    )


def login_page(error: str = ""):
    message = error.strip()[:240]
    return public_page(
        Section(
            Div(
                Span("Secure workspace", cls="kicker"),
                H1("Sign in to FastAccounts"),
                P("Use an approved Google account. Local credentials and open registration are intentionally not enabled in this pilot."),
                Div(message, cls="error") if message else None,
                A("Continue with Google" if google_auth.enabled() else "Google sign-in is not configured", href="/auth/google", cls="button primary google"),
                P("Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and the exact callback URI in your ignored .env.") if not google_auth.enabled() else None,
                cls="auth-card",
            ),
            cls="auth-wrap",
        ),
        title="Sign in",
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
