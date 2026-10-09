"""Email/password sign-up, sign-in and reset beside Google SSO (unit, integration, security)."""
from __future__ import annotations

import hashlib
import logging
import re
import time

import pytest
from starlette.testclient import TestClient

from web import account_auth
from web.account_auth import accounts, hash_password, needs_rehash, normalize_email, verify_password

OWNER = "owner@example.test"
PASSWORD = "correct horse battery"
CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')
LINK = re.compile(r"https://books\.example\.test/auth/local/(verify|reset)/([A-Za-z0-9_\-]+)")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    monkeypatch.setenv("FASTACCOUNTS_DB", str(tmp_path / "auth.sqlite"))
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("FASTACCOUNTS_PUBLIC_URL", "https://books.example.test")
    for key in ("GOOGLE_ALLOWED_DOMAINS", "GOOGLE_ALLOWED_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    org = OrganisationService(db).create(name="Synthetic Auth OÜ", country_code="EE", entity_type="EE_OU",
                                         owner_email=OWNER)
    mails: list[dict] = []

    def fake_send(to, subject, html_body, text_body):
        mails.append({"to": to, "subject": subject, "html": html_body, "text": text_body})
        return True

    monkeypatch.setattr(account_auth, "send_email", fake_send)
    yield {"db": db, "org": org, "mails": mails}
    database.reset_database_cache()


def client():
    from web_app import app
    return TestClient(app, base_url="https://testserver")


def csrf(c, path="/login"):
    return CSRF.search(c.get(path).text).group(1)


def post(c, path, data, page="/login"):
    return c.post(path, data={"csrf_token": csrf(c, page), **data}, follow_redirects=False)


def link(mail):
    purpose, token = LINK.search(mail["text"]).groups()
    return purpose, token


def register_and_verify(c, env, email=OWNER, password=PASSWORD):
    assert post(c, "/auth/local/register", {"name": "Owner", "email": email, "password": password}).status_code == 200
    _, token = link(env["mails"][-1])
    response = post(c, "/auth/local/verify", {"token": token, "password": password}, f"/auth/local/verify/{token}")
    assert response.status_code == 303 and response.headers["location"] == "/app"
    return token


def notice(text):
    match = re.search(r'class="(?:auth-notice|error)"[^>]*>([^<]+)<', text)
    return match.group(1) if match else ""


# ---------------------------------------------------------------- unit
def test_scrypt_hash_roundtrip_salted_and_owasp_cost():
    encoded = hash_password(PASSWORD)
    assert encoded.startswith("scrypt$16384$8$5$") and PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded) and not verify_password("wrong password!", encoded)
    assert hash_password(PASSWORD) != encoded
    assert not needs_rehash(encoded)
    for broken in ("", None, "plain", "scrypt$x$y$z", "bcrypt$1$2$3$4$5"):
        assert not verify_password(PASSWORD, broken)


def test_sister_product_scrypt_format_still_verifies_and_is_upgraded():
    import base64
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(PASSWORD.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    legacy = "scrypt$16384$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()
    assert verify_password(PASSWORD, legacy) and needs_rehash(legacy)


def test_email_normalisation_and_password_bounds():
    assert normalize_email("  Owner@Example.TEST ") == OWNER
    assert normalize_email("not-an-email") == "" and normalize_email("a@b") == ""
    assert not account_auth.valid_password("short") and account_auth.valid_password("x" * 10)
    assert not account_auth.valid_password("x" * 1025)


def test_client_address_uses_last_proxy_hop():
    from types import SimpleNamespace
    request = SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, client=SimpleNamespace(host="10.0.0.2"))
    assert account_auth.client_address(request) == "203.0.113.9"
    assert account_auth.client_address(SimpleNamespace(headers={}, client=SimpleNamespace(host="10.0.0.2"))) == "10.0.0.2"


# ---------------------------------------------------------------- pages
@pytest.mark.parametrize("lang", ["en", "et", "lv", "lt"])
def test_login_page_offers_google_and_email_in_every_language(env, lang):
    from web import i18n
    c = client()
    c.get(f"/set-lang/{lang}?next=/login")
    text = c.get("/login").text
    assert 'href="/auth/google"' in text and 'action="/auth/local/login"' in text
    assert i18n.t("auth.submit_signin", lang) in text and i18n.t("auth.forgot_link", lang) in text
    assert 'name="csrf_token"' in text
    register = c.get("/login?tab=register").text
    assert 'action="/auth/local/register"' in register and 'autocomplete="new-password"' in register
    assert 'action="/auth/local/forgot"' in c.get("/login?tab=forgot").text


def test_token_pages_are_not_cached_or_leaked_by_referrer(env):
    c = client()
    for path in ("/auth/local/reset/abc", "/auth/local/verify/abc"):
        response = c.get(path)
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "no-referrer" and response.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------- sign-up and verification
def test_signup_requires_email_confirmation_with_the_chosen_password(env):
    c = client()
    response = post(c, "/auth/local/register", {"name": "Owner", "email": OWNER, "password": PASSWORD})
    assert response.status_code == 200 and "confirmation link" in notice(response.text)
    mail = env["mails"][-1]
    assert mail["to"] == OWNER and link(mail)[0] == "verify"
    assert post(c, "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 401
    _, token = link(mail)
    page = f"/auth/local/verify/{token}"
    assert post(c, "/auth/local/verify", {"token": token, "password": "someone else's guess"}, page).status_code == 400
    response = post(c, "/auth/local/verify", {"token": token, "password": PASSWORD}, page)
    assert response.status_code == 303 and response.headers["location"] == "/app"
    assert "workspace-app" in c.get("/app").text
    assert [o["id"] for o in c.get("/api/organisations").json()] == [env["org"]["id"]]
    other = client()
    assert post(other, "/auth/local/verify", {"token": token, "password": PASSWORD}, page).status_code == 400


def test_preregistration_by_a_stranger_cannot_take_over_the_address(env):
    attacker, victim = client(), client()
    post(attacker, "/auth/local/register", {"name": "X", "email": OWNER, "password": "attacker-password"})
    _, token = link(env["mails"][-1])
    # The mailbox owner clicks the link but does not know the attacker's password.
    assert post(victim, "/auth/local/verify", {"token": token, "password": PASSWORD},
                f"/auth/local/verify/{token}").status_code == 400
    assert post(attacker, "/auth/local/login", {"email": OWNER, "password": "attacker-password"}).status_code == 401
    # A Google login for the same address discards the unproven password.
    account = accounts.link_google(OWNER, "Owner")
    assert account["email_verified"] == 1 and account["password_hash"] is None
    assert post(attacker, "/auth/local/verify", {"token": token, "password": "attacker-password"},
                f"/auth/local/verify/{token}").status_code == 400


def test_registration_outcome_does_not_reveal_whether_an_account_exists(env):
    c = client()
    register_and_verify(c, env)
    sent = len(env["mails"])
    texts = []
    for email in (OWNER, "stranger@example.test", "new-invitee@example.test"):
        response = post(client(), "/auth/local/register", {"name": "N", "email": email, "password": PASSWORD})
        texts.append((response.status_code, notice(response.text)))
    assert len(set(texts)) == 1
    assert len(env["mails"]) == sent  # neither the existing nor the unknown address got mail
    assert env["db"].one("SELECT 1 FROM user_accounts WHERE email='stranger@example.test'") is None


def test_invited_user_can_register_verify_and_accept_invitation(env):
    from governance import GovernanceService
    invitation, raw = GovernanceService(env["db"]).invite(env["org"]["id"], email="invitee@example.test",
                                                         role="viewer", actor=OWNER)
    c = client()
    register_and_verify(c, env, email="invitee@example.test")
    token = c.get("/api/csrf").json()["csrf_token"]
    response = c.post("/api/invitations/accept", json={"token": raw}, headers={"X-CSRF-Token": token})
    assert response.status_code in (200, 201), response.text
    assert [o["id"] for o in c.get("/api/organisations").json()] == [env["org"]["id"]]


def test_mail_failure_keeps_generic_message(env, monkeypatch, caplog):
    monkeypatch.setattr(account_auth, "send_email", lambda *a: False)
    response = post(client(), "/auth/local/register", {"name": "O", "email": OWNER, "password": PASSWORD})
    assert response.status_code == 200 and "confirmation link" in notice(response.text)


# ---------------------------------------------------------------- sign-in
def test_signin_errors_are_identical_for_unknown_wrong_and_unverified(env):
    c = client()
    register_and_verify(c, env)
    post(client(), "/auth/local/register", {"name": "I", "email": "pending@example.test", "password": PASSWORD})
    outcomes = set()
    for email, password in ((OWNER, "wrong password!"), ("nobody@example.test", PASSWORD),
                            ("pending@example.test", PASSWORD)):
        response = post(client(), "/auth/local/login", {"email": email, "password": password})
        outcomes.add((response.status_code, notice(response.text)))
    assert len(outcomes) == 1 and next(iter(outcomes))[0] == 401


def test_signin_rotates_the_session_and_csrf_token(env):
    c = client()
    register_and_verify(c, env)
    c.get("/logout")
    before = csrf(c)
    cookie_before = c.cookies.get("session_")
    response = c.post("/auth/local/login", data={"csrf_token": before, "email": OWNER, "password": PASSWORD},
                      follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/app"
    assert c.cookies.get("session_") != cookie_before
    after = c.get("/api/csrf").json()["csrf_token"]
    assert after != before


def test_signin_honours_only_local_next_paths(env):
    c = client()
    register_and_verify(c, env)
    c.get("/logout")
    response = post(c, "/auth/local/login", {"email": OWNER, "password": PASSWORD, "next": "//evil.example/x"})
    assert response.headers["location"] == "/app"
    c.get("/logout")
    response = post(c, "/auth/local/login", {"email": OWNER, "password": PASSWORD, "next": "/integrations"})
    assert response.headers["location"] == "/integrations"


def test_signin_lockout_after_repeated_failures_even_with_right_password(env):
    c = client()
    register_and_verify(c, env)
    c.get("/logout")
    for _ in range(account_auth.LIMITS["login"][0]):
        assert post(client(), "/auth/local/login", {"email": OWNER, "password": "wrong password!"}).status_code == 401
    response = post(client(), "/auth/local/login", {"email": OWNER, "password": PASSWORD})
    assert response.status_code == 429 and "Too many attempts" in notice(response.text)


def test_per_address_throttle_for_spraying_many_accounts(env, monkeypatch):
    monkeypatch.setitem(account_auth.LIMITS, "login_ip", (3, 900))
    for index in range(3):
        post(client(), "/auth/local/login", {"email": f"user{index}@example.test", "password": PASSWORD})
    assert post(client(), "/auth/local/login", {"email": "user9@example.test", "password": PASSWORD}).status_code == 429


def test_successful_signin_clears_failure_counter(env):
    c = client()
    register_and_verify(c, env)
    for _ in range(3):
        post(client(), "/auth/local/login", {"email": OWNER, "password": "wrong password!"})
    assert post(client(), "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 303
    assert not accounts.limited(OWNER, "login")


@pytest.mark.parametrize("path,page", [
    ("/auth/local/login", "/login"), ("/auth/local/register", "/login"), ("/auth/local/forgot", "/login"),
    ("/auth/local/reset", "/auth/local/reset/x"), ("/auth/local/verify", "/auth/local/verify/x"),
])
def test_every_auth_form_requires_the_session_csrf_token(env, path, page):
    c = client()
    c.get(page)
    data = {"email": OWNER, "password": PASSWORD, "name": "O", "token": "x"}
    assert c.post(path, data=data, follow_redirects=False).status_code == 403
    assert c.post(path, data={**data, "csrf_token": "forged"}, follow_redirects=False).status_code == 403


# ---------------------------------------------------------------- reset
def test_reset_tokens_are_hashed_single_use_and_expire_in_an_hour(env):
    c = client()
    register_and_verify(c, env)
    response = post(client(), "/auth/local/forgot", {"email": OWNER})
    assert response.status_code == 200
    purpose, token = link(env["mails"][-1])
    assert purpose == "reset"
    row = env["db"].one("SELECT * FROM auth_tokens WHERE purpose='reset' AND used_at IS NULL")
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest() and token not in str(row)
    assert abs(int(row["expires_at"]) - (int(time.time()) + 3600)) < 30
    r = client()
    assert post(r, "/auth/local/reset", {"token": token, "password": "short"}, f"/auth/local/reset/{token}").status_code == 400
    response = post(r, "/auth/local/reset", {"token": token, "password": "brand new password"}, f"/auth/local/reset/{token}")
    assert response.status_code == 303 and response.headers["location"] == "/login?notice=password_reset"
    assert post(r, "/auth/local/reset", {"token": token, "password": "another password!"},
                f"/auth/local/reset/{token}").status_code == 400
    assert post(client(), "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 401
    assert post(client(), "/auth/local/login", {"email": OWNER, "password": "brand new password"}).status_code == 303


def test_expired_and_superseded_reset_links_are_rejected(env):
    register_and_verify(client(), env)
    post(client(), "/auth/local/forgot", {"email": OWNER})
    _, first = link(env["mails"][-1])
    post(client(), "/auth/local/forgot", {"email": OWNER})
    _, second = link(env["mails"][-1])
    assert accounts.reset_password(first, "brand new password") is None
    with env["db"].transaction() as tx:
        tx.execute("UPDATE auth_tokens SET expires_at=? WHERE purpose='reset'", (int(time.time()) - 1,))
    assert accounts.reset_password(second, "brand new password") is None


def test_reset_signs_out_every_other_session(env):
    browser_a = client()
    register_and_verify(browser_a, env)
    assert browser_a.get("/api/organisations").status_code == 200
    post(client(), "/auth/local/forgot", {"email": OWNER})
    _, token = link(env["mails"][-1])
    post(client(), "/auth/local/reset", {"token": token, "password": "brand new password"}, f"/auth/local/reset/{token}")
    assert browser_a.get("/api/organisations").status_code == 401
    assert browser_a.get("/app", follow_redirects=False).headers["location"].startswith("/login")
    browser_b = client()
    assert post(browser_b, "/auth/local/login", {"email": OWNER, "password": "brand new password"}).status_code == 303
    assert browser_b.get("/api/organisations").status_code == 200


def test_forgot_does_not_reveal_accounts_and_is_rate_limited(env):
    register_and_verify(client(), env)
    a = post(client(), "/auth/local/forgot", {"email": OWNER})
    b = post(client(), "/auth/local/forgot", {"email": "nobody@example.test"})
    assert (a.status_code, notice(a.text)) == (b.status_code, notice(b.text))
    assert [m["to"] for m in env["mails"] if "reset" in m["text"]] == [OWNER]
    limit = account_auth.LIMITS["forgot"][0]
    for _ in range(limit - 1):
        post(client(), "/auth/local/forgot", {"email": OWNER})
    assert post(client(), "/auth/local/forgot", {"email": OWNER}).status_code == 429


def test_token_forms_are_throttled_per_client(env, monkeypatch):
    monkeypatch.setitem(account_auth.LIMITS, "token_ip", (2, 900))
    c = client()
    for _ in range(2):
        post(c, "/auth/local/reset", {"token": "guess", "password": "brand new password"}, "/auth/local/reset/guess")
    assert post(c, "/auth/local/reset", {"token": "guess", "password": "brand new password"},
                "/auth/local/reset/guess").status_code == 429


# ---------------------------------------------------------------- Google linking
def test_google_only_member_sets_a_password_through_reset_and_keeps_one_identity(env):
    google = accounts.link_google(OWNER, "Owner From Google")
    assert google["google_linked"] == 1 and google["password_hash"] is None
    assert post(client(), "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 401
    post(client(), "/auth/local/forgot", {"email": OWNER})
    _, token = link(env["mails"][-1])
    post(client(), "/auth/local/reset", {"token": token, "password": PASSWORD}, f"/auth/local/reset/{token}")
    c = client()
    assert post(c, "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 303
    assert accounts.link_google(OWNER, "Ignored")["id"] == google["id"]
    assert env["db"].scalar("SELECT COUNT(*) FROM user_accounts") == 1


def test_member_without_any_account_row_can_set_password_via_reset(env):
    # Members who signed in with Google before 0.4.0 have no user_accounts row yet.
    assert accounts.get(OWNER) is None
    post(client(), "/auth/local/forgot", {"email": OWNER})
    _, token = link(env["mails"][-1])
    post(client(), "/auth/local/reset", {"token": token, "password": PASSWORD}, f"/auth/local/reset/{token}")
    assert post(client(), "/auth/local/login", {"email": OWNER, "password": PASSWORD}).status_code == 303


def test_google_callback_links_account_and_rotates_session(env, monkeypatch):
    from web import google_auth
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setattr(google_auth, "exchange", lambda request, code: {"email": OWNER, "name": "Owner"})
    register_and_verify(client(), env)
    c = client()
    pre_login_csrf = csrf(c)
    start = c.get("/auth/google", follow_redirects=False)
    assert "accounts.google.com" in start.headers["location"]
    state = re.search(r"state=([^&]+)", start.headers["location"]).group(1)
    response = c.get(f"/auth/google/callback?code=x&state={state}", follow_redirects=False)
    assert response.headers["location"] == "/app"
    assert c.get("/api/organisations").status_code == 200
    assert c.get("/api/csrf").json()["csrf_token"] != pre_login_csrf
    account = accounts.get(OWNER)
    assert account["google_linked"] == 1 and account["password_hash"]  # verified password is kept
    assert env["db"].scalar("SELECT COUNT(*) FROM user_accounts WHERE email=?", (OWNER,)) == 1


def test_sessions_from_before_this_release_stay_valid_until_a_reset(env):
    assert account_auth.session_user_valid({"email": OWNER})
    accounts.link_google(OWNER)
    assert account_auth.session_user_valid({"email": OWNER})
    with env["db"].transaction() as tx:
        tx.execute("UPDATE user_accounts SET session_version=2 WHERE email=?", (OWNER,))
    assert not account_auth.session_user_valid({"email": OWNER})
    assert account_auth.session_user_valid({"email": OWNER, "sv": 2})


# ---------------------------------------------------------------- mail
def test_without_mail_configuration_requests_log_and_show_generic_message(env, monkeypatch, caplog):
    monkeypatch.undo()  # restore the real sender, then re-apply the isolated database
    monkeypatch.setenv("FASTACCOUNTS_DB", str(env["db"].path))
    monkeypatch.setenv("FASTACCOUNTS_PUBLIC_URL", "https://books.example.test")
    monkeypatch.delenv("POSTMARK_API_TOKEN", raising=False)
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    caplog.set_level(logging.WARNING, logger="fastaccounts.auth")
    response = post(client(), "/auth/local/forgot", {"email": OWNER})
    assert response.status_code == 200 and "reset link" in notice(response.text)
    assert "POSTMARK_API_TOKEN and FROM_EMAIL are not configured" in caplog.text


def test_links_are_built_from_configuration_not_the_host_header(env, monkeypatch, caplog):
    monkeypatch.delenv("FASTACCOUNTS_PUBLIC_URL", raising=False)
    monkeypatch.delenv("FASTSME_PUBLIC_URL", raising=False)
    caplog.set_level(logging.WARNING, logger="fastaccounts.auth")
    c = client()
    c.post("/auth/local/forgot", data={"csrf_token": csrf(c), "email": OWNER}, headers={"host": "evil.example"})
    assert env["mails"] == [] and "FASTACCOUNTS_PUBLIC_URL is not configured" in caplog.text


def test_postmark_request_uses_sister_env_names_and_never_logs_the_token(monkeypatch, caplog):
    captured = {}

    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(request, timeout):
        captured["url"], captured["headers"], captured["body"] = request.full_url, dict(request.header_items()), request.data
        return Response()

    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-server-token")
    monkeypatch.setenv("FROM_EMAIL", "accounts@example.test")
    monkeypatch.setattr(account_auth, "urlopen", fake_urlopen)
    caplog.set_level(logging.DEBUG)
    assert account_auth.send_email("to@example.test", "Subject", "<p>x</p>", "x")
    assert captured["url"] == "https://api.postmarkapp.com/email"
    assert captured["headers"]["X-postmark-server-token"] == "synthetic-server-token"
    assert b'"From": "accounts@example.test"' in captured["body"] and b'"MessageStream": "outbound"' in captured["body"]
    assert "synthetic-server-token" not in caplog.text


@pytest.mark.parametrize("lang,subject", [("en", "Reset your FastAccounts password"), ("et", "FastAccountsi parooli lähtestamine")])
def test_reset_mail_is_localised(env, lang, subject):
    register_and_verify(client(), env)
    c = client()
    c.get(f"/set-lang/{lang}?next=/login")
    post(c, "/auth/local/forgot", {"email": OWNER})
    assert env["mails"][-1]["subject"] == subject


def test_test_auth_and_api_test_header_still_work(env):
    c = client()
    assert "workspace-app" in c.get("/auth/test?email=" + OWNER).text
    assert c.get("/api/organisations").status_code == 200
    assert client().get("/api/organisations", headers={"x-test-user": OWNER}).status_code == 200


def test_sign_out_ends_the_session_but_keeps_the_language(env):
    c = client()
    register_and_verify(c, env)
    c.get("/set-lang/et?next=/app")
    c.get("/logout")
    assert c.get("/api/organisations").status_code == 401
    assert 'lang="et"' in c.get("/login").text
