"""FastAccounts — open bookkeeping for UK and Estonian businesses."""
from __future__ import annotations

import hmac
import os
import secrets
from urllib.parse import quote, unquote, urlsplit

from dotenv import load_dotenv

load_dotenv()

from fasthtml.common import RedirectResponse, fast_app, serve
from starlette.responses import JSONResponse
from starlette.responses import PlainTextResponse

import integrations
import version
from api_app import api
from database import get_database
from web import google_auth, i18n
from web.public import integrations_page, landing_page, login_page, workspace_page


SECRET = os.getenv("FASTACCOUNTS_SECRET", "").strip() or secrets.token_hex(32)
PORT = int(os.getenv("FASTACCOUNTS_PORT", "5012"))
ENV_LABEL = os.getenv("FASTACCOUNTS_ENV_LABEL", "FastAccounts")
RELOAD = os.getenv("FASTACCOUNTS_RELOAD", "false").lower() == "true"
SESSION_HTTPS_ONLY = os.getenv("FASTACCOUNTS_PUBLIC_URL", "").lower().startswith("https://")

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, max_age=8 * 60 * 60,
                   same_site="lax", sess_https_only=SESSION_HTTPS_ONLY)
app.mount("/api", api)


@app.on_event("startup")
async def migrate_database():
    get_database().migrate()


@rt("/")
def home(session, request):
    if session.get("user"):
        return RedirectResponse("/app", status_code=303)
    return landing_page(i18n.get_lang(session, request))


@rt("/integrations")
def integration_catalogue(session, request):
    return integrations_page(i18n.get_lang(session, request))


@rt("/login")
def login(session, request, error: str = ""):
    return login_page(error, i18n.get_lang(session, request))


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
    session["user"] = user
    session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/app", status_code=303)


@rt("/auth/test")
def test_login(session, email: str = "demo@fastaccounts.local"):
    """Local/UAT convenience route; hard-disabled unless explicitly enabled."""
    if os.getenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "").lower() != "true":
        return PlainTextResponse("Not found", status_code=404)
    session["user"] = {"email": email.strip().lower(), "name": "Synthetic Demo User"}
    session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/app", status_code=303)


@rt("/app")
def workspace(session):
    user = session.get("user")
    if not user:
        return RedirectResponse(f"/login?next={quote('/app', safe='')}", status_code=303)
    return workspace_page(user)


@rt("/logout")
def logout(session):
    session.clear()
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
