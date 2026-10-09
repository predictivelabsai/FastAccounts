"""FastAccounts — open bookkeeping for UK and Estonian businesses."""
from __future__ import annotations

import hmac
import os
import secrets
from urllib.parse import quote, unquote, urlsplit

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import RedirectResponse, fast_app, serve, to_xml
from starlette.responses import HTMLResponse
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse

import automation
import integrations
import version
from api_app import api
from database import get_database
from web import account_auth, google_auth, i18n
from web.account_auth import accounts, client_address, csrf_ok, establish_session, form_csrf
from web.public import (about_page, changelog_page, contact_page,
                        integrations_page, landing_page, login_page, privacy_page,
                        password_token_page, roadmap_page, security_page,
                        terms_page, workspace_page)


def _page_language(session, request):
    # Explicit session choice wins; the demo override precedes browser detection.
    default = os.getenv("FASTACCOUNTS_DEFAULT_LANG", "").strip().lower()
    if not session.get("lang") and default in i18n.SUPPORTED_LANGS:
        session["lang"] = default
    return i18n.get_lang(session, request)



SECRET = os.getenv("FASTACCOUNTS_SECRET", "").strip() or secrets.token_hex(32)
PORT = int(os.getenv("FASTACCOUNTS_PORT", "5012"))
ENV_LABEL = os.getenv("FASTACCOUNTS_ENV_LABEL", "FastAccounts")
RELOAD = os.getenv("FASTACCOUNTS_RELOAD", "false").lower() == "true"
SESSION_HTTPS_ONLY = os.getenv("FASTACCOUNTS_PUBLIC_URL", "").lower().startswith("https://")

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, max_age=8 * 60 * 60,
                   same_site="lax", sess_https_only=SESSION_HTTPS_ONLY)
app.mount("/api", api)
# API documents must resolve before FastHTML's catch-all static extension route.
app.router.routes.insert(0, app.router.routes.pop())


@app.on_event("startup")
async def migrate_database():
    get_database().migrate()
    automation.start_automation_worker()


@rt("/")
def home(session, request):
    if session.get("user"):
        return RedirectResponse("/app", status_code=303)
    return landing_page(_page_language(session, request))


@rt("/integrations")
def integration_catalogue(session, request):
    return integrations_page(_page_language(session, request))


@rt("/security")
def security(session, request):
    return security_page(_page_language(session, request))


@rt("/privacy")
def privacy(session, request):
    return privacy_page(_page_language(session, request))


@rt("/about")
def about(session, request):
    return about_page(_page_language(session, request))


@rt("/contact")
def contact(session, request):
    return contact_page(_page_language(session, request))


@rt("/terms")
def terms(session, request):
    return terms_page(_page_language(session, request))


@rt("/roadmap")
def roadmap(session, request):
    return roadmap_page(_page_language(session, request))


@rt("/changelog")
def changelog(session, request):
    return changelog_page(_page_language(session, request))


NOTICES = {"registered", "reset_sent", "password_reset", "verified"}


@rt("/login")
def login(session, request, error: str = "", tab: str = "signin", notice: str = "", next: str = ""):
    lang = _page_language(session, request)
    message = i18n.t(f"auth.notice_{notice}", lang) if notice in NOTICES else ""
    next_path = _safe_return_path(next) if next else ""
    return login_page(error, lang, tab=tab, notice=message, csrf=form_csrf(session),
                      next_path="" if next_path == "/" else next_path)


def _safe_return_path(value: str) -> str:
    """Preserve a local public route without allowing an external redirect."""
    value = value or "/"
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or not decoded_path.startswith("/")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(ord(character) < 32 for character in unquote(value))
    ):
        return "/"
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


@rt("/set-lang/{code}")
def set_language(code: str, session, next: str = "/"):
    i18n.set_lang(session, code)
    return RedirectResponse(_safe_return_path(next), status_code=303)


@rt("/auth/google")
def google_start(request, session):
    if not google_auth.enabled():
        return RedirectResponse("/login?error=Google+sign-in+is+not+configured", status_code=303)
    state = google_auth.new_state()
    session["google_oauth_state"] = state
    return RedirectResponse(google_auth.authorize_url(request, state), status_code=303)


@rt("/auth/google/callback")
def google_callback(request, session, code: str = "", state: str = ""):
    expected = session.pop("google_oauth_state", "")
    if not code or not expected or not hmac.compare_digest(expected, state):
        return RedirectResponse("/login?error=Google+sign-in+state+was+invalid", status_code=303)
    user = google_auth.exchange(request, code)
    if not user:
        return RedirectResponse("/login?error=Google+sign-in+failed", status_code=303)
    account = accounts.link_google(user["email"], user.get("name", ""))
    establish_session(session, {**(account or {}), **user, "session_version": (account or {}).get("session_version", 1)}, "google")
    return RedirectResponse("/app", status_code=303)


@rt("/auth/test")
def test_login(session, email: str = "demo@fastaccounts.local"):
    """Local/UAT convenience route; hard-disabled unless explicitly enabled."""
    if os.getenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "").lower() != "true":
        return PlainTextResponse("Not found", status_code=404)
    email = email.strip().lower()
    account = accounts.get(email) or {}
    establish_session(session, {"email": email, "name": "Demo Kasutaja",
                                "session_version": account.get("session_version", 1)}, "test")
    return RedirectResponse("/app", status_code=303)


# ---------------------------------------------------------------- email and password
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _auth_text(key: str, lang: str) -> str:
    return i18n.t(f"auth.{key}", lang)


def _login_response(session, request, lang, *, tab, status, error="", notice="", email="", next_path=""):
    page = login_page(error, lang, tab=tab, notice=notice, csrf=form_csrf(session), email=email,
                      next_path=next_path)
    return HTMLResponse("<!doctype html>\n" + to_xml(page), status_code=status, headers=NO_STORE)


async def _auth_form(request):
    form = await request.form()
    return {key: (value if isinstance(value, str) else "") for key, value in form.items()}


@rt("/auth/local/login", methods=["POST"])
async def local_login(request, session):
    form, lang = await _auth_form(request), _page_language(session, request)
    email, ip = account_auth.normalize_email(form.get("email")), client_address(request)
    next_path = _safe_return_path(form.get("next", "")) if form.get("next") else ""
    respond = lambda status, key: _login_response(session, request, lang, tab="signin", status=status,
                                                  error=_auth_text(key, lang), email=email, next_path=next_path)
    if not csrf_ok(session, form.get("csrf_token")):
        return respond(403, "error_session_expired")
    if accounts.limited(ip, "login_ip") or (email and accounts.limited(email, "login")):
        return respond(429, "error_rate_limited")
    account = accounts.authenticate(email, form.get("password", "")) if email else None
    if not account:
        accounts.hit(ip, "login_ip")
        if email:
            accounts.hit(email, "login")
        return respond(401, "error_credentials")
    accounts.clear(email, "login")
    establish_session(session, account, "password")
    target = next_path if next_path and next_path != "/" else "/app"
    return RedirectResponse(target, status_code=303)


@rt("/auth/local/register", methods=["POST"])
async def local_register(request, session):
    form, lang = await _auth_form(request), _page_language(session, request)
    email, ip = account_auth.normalize_email(form.get("email")), client_address(request)
    respond = lambda status, error="", notice="": _login_response(
        session, request, lang, tab="register", status=status, error=error, notice=notice,
        email=form.get("email", "")[:254])
    if not csrf_ok(session, form.get("csrf_token")):
        return respond(403, _auth_text("error_session_expired", lang))
    if not email or not account_auth.valid_password(form.get("password", "")):
        return respond(400, _auth_text("error_invalid_input", lang))
    if not accounts.consume(ip, "register_ip") or not accounts.consume(email, "register"):
        return respond(429, _auth_text("error_rate_limited", lang))
    accounts.register(email, form.get("password", ""), form.get("name", ""), lang)
    return respond(200, notice=_auth_text("notice_registered", lang))


@rt("/auth/local/forgot", methods=["POST"])
async def local_forgot(request, session):
    form, lang = await _auth_form(request), _page_language(session, request)
    email, ip = account_auth.normalize_email(form.get("email")), client_address(request)
    respond = lambda status, error="", notice="": _login_response(
        session, request, lang, tab="forgot", status=status, error=error, notice=notice,
        email=form.get("email", "")[:254])
    if not csrf_ok(session, form.get("csrf_token")):
        return respond(403, _auth_text("error_session_expired", lang))
    if not email:
        return respond(400, _auth_text("error_invalid_email", lang))
    if not accounts.consume(ip, "forgot_ip") or not accounts.consume(email, "forgot"):
        return respond(429, _auth_text("error_rate_limited", lang))
    accounts.request_reset(email, lang)
    return respond(200, notice=_auth_text("notice_reset_sent", lang))


def _token_page(session, request, purpose, token, *, status=200, error_key=""):
    lang = _page_language(session, request)
    page = password_token_page(purpose, token, lang, csrf=form_csrf(session),
                               error=_auth_text(error_key, lang) if error_key else "")
    return HTMLResponse("<!doctype html>\n" + to_xml(page), status_code=status, headers=NO_STORE)


@rt("/auth/local/reset/{token}", methods=["GET"])
def local_reset_page(token: str, session, request):
    return _token_page(session, request, "reset", token[:200])


@rt("/auth/local/verify/{token}", methods=["GET"])
def local_verify_page(token: str, session, request):
    return _token_page(session, request, "verify", token[:200])


@rt("/auth/local/reset", methods=["POST"])
async def local_reset_submit(request, session):
    form = await _auth_form(request)
    token = form.get("token", "")[:200]
    if not csrf_ok(session, form.get("csrf_token")):
        return _token_page(session, request, "reset", token, status=403, error_key="error_session_expired")
    if not accounts.consume(client_address(request), "token_ip"):
        return _token_page(session, request, "reset", token, status=429, error_key="error_rate_limited")
    if not account_auth.valid_password(form.get("password", "")):
        return _token_page(session, request, "reset", token, status=400, error_key="error_password_length")
    if not accounts.reset_password(token, form.get("password", "")):
        return _token_page(session, request, "reset", token, status=400, error_key="error_link_invalid")
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return RedirectResponse("/login?notice=password_reset", status_code=303)


@rt("/auth/local/verify", methods=["POST"])
async def local_verify_submit(request, session):
    form = await _auth_form(request)
    token = form.get("token", "")[:200]
    if not csrf_ok(session, form.get("csrf_token")):
        return _token_page(session, request, "verify", token, status=403, error_key="error_session_expired")
    if not accounts.consume(client_address(request), "token_ip"):
        return _token_page(session, request, "verify", token, status=429, error_key="error_rate_limited")
    account = accounts.confirm_email(token, form.get("password", ""))
    if not account:
        return _token_page(session, request, "verify", token, status=400, error_key="error_verify_failed")
    if not google_auth.access_allowed(account["email"]):
        return RedirectResponse("/login?notice=verified", status_code=303)
    establish_session(session, account, "password")
    return RedirectResponse("/app", status_code=303)


@rt("/app")
def workspace(session, request):
    user = session.get("user")
    if user and not account_auth.session_user_valid(user):
        session.clear()
        user = None
    if not user:
        return RedirectResponse(f"/login?next={quote('/app', safe='')}", status_code=303)
    return workspace_page(user, _page_language(session, request))


@rt("/logout")
def logout(session):
    lang = session.get("lang")
    session.clear()
    if lang:
        session["lang"] = lang
    return RedirectResponse("/", status_code=303)


@rt("/healthz")
def healthz():
    database = get_database()
    try:
        migration_count = int(database.scalar("SELECT COUNT(*) FROM schema_migrations") or 0)
        database_status = "ok"
    except Exception:
        migration_count, database_status = 0, "error"
    return JSONResponse({
        "status": "ok" if database_status == "ok" else "degraded",
        "product": "FastAccounts",
        "version": version.VERSION,
        "environment": ENV_LABEL,
        "database": {"status": database_status, "dialect": database.dialect,
                     "schema": database.schema if database.dialect == "postgres" else None,
                     "migrations": migration_count},
        "integrations": len(integrations.CATALOGUE),
        "live_integrations": 0,
    }, status_code=200 if database_status == "ok" else 503)


if __name__ == "__main__":
    serve(port=PORT, reload=RELOAD)
