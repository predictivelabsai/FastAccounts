"""Minimal server-side Google OpenID Connect flow."""
from __future__ import annotations

import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _config() -> tuple[str, str, str]:
    return (
        os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        os.getenv("GOOGLE_REDIRECT_URI", "").strip(),
    )


def enabled() -> bool:
    client_id, client_secret, _ = _config()
    return bool(client_id and client_secret)


def new_state() -> str:
    return secrets.token_urlsafe(32)


def callback_uri(request) -> str:
    _, _, configured = _config()
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}/auth/google/callback"


def authorize_url(request, state: str) -> str:
    client_id, _, _ = _config()
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": callback_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    })


def _json_request(url: str, *, data=None, token: str | None = None) -> dict:
    body = urlencode(data).encode() if data else None
    headers = {"Accept": "application/json"}
    if data:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=body, headers=headers), timeout=20) as response:
        return json.loads(response.read())


def exchange(request, code: str) -> dict | None:
    client_id, client_secret, _ = _config()
    try:
        token = _json_request("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": callback_uri(request),
            "grant_type": "authorization_code",
        })
        info = _json_request(
            "https://openidconnect.googleapis.com/v1/userinfo",
            token=token.get("access_token"),
        )
    except (HTTPError, URLError, TimeoutError, ValueError, TypeError):
        return None
    email = (info.get("email") or "").strip().lower()
    if not email or info.get("email_verified") is False:
        return None
    domains = {x.strip().lower() for x in os.getenv("GOOGLE_ALLOWED_DOMAINS", "").split(",") if x.strip()}
    emails = {x.strip().lower() for x in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",") if x.strip()}
    domain = email.rsplit("@", 1)[-1]
    configured_match = email in emails or domain in domains
    if not configured_match:
        try:
            from database import get_database
            db = get_database()
            known = db.one(
                "SELECT email FROM memberships WHERE lower(email)=lower(?) "
                "UNION SELECT email FROM invitations WHERE lower(email)=lower(?) AND status='Pending' LIMIT 1",
                (email, email),
            )
            bootstrap = not (domains or emails) and int(db.scalar("SELECT COUNT(*) FROM organisations") or 0) == 0
        except Exception:
            known, bootstrap = None, False
        if not known and not bootstrap:
            return None
    return {"email": email, "name": info.get("name") or email}
