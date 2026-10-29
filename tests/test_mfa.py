"""Offline MFA engine, account persistence and browser-route regressions."""

from tests.migration_catalogue import catalogue, catalogue_after

import base64
import json
import re
import socket
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from web import account_auth, totp, i18n
from web.account_auth import accounts, AccountStore, hash_password, token_digest

EMAIL = "owner@example.test"
PASSWORD = "correct horse battery"
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect

    def blocked(sock, address, *args, **kwargs):
        # Windows asyncio uses loopback for its local socketpair.
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original(sock, address, *args, **kwargs)
        raise AssertionError("Live network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.mark.parametrize("now,expected", [(59, "287082"), (1111111109, "081804"),
    (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")])
def test_rfc6238_sha1_vectors(now, expected):
    # RFC 6238 Appendix B eight-digit SHA-1 values reduced to six digits.
    assert totp.code(RFC_SECRET, now // 30) == expected


@pytest.mark.parametrize("step,expected", enumerate(["755224", "287082", "359152", "969429", "338314",
                                                     "254676", "287922", "162583", "399871", "520489"]))
def test_rfc4226_hotp_values(step, expected):
    assert totp.code(RFC_SECRET, step) == expected


@pytest.mark.parametrize("offset", [-2, -1, 0, 1, 2])
def test_window_replay(offset):
    value = totp.code(RFC_SECRET, 100 + offset)
    assert totp.verify(RFC_SECRET, value, None, 3000) == (100 + offset if abs(offset) <= 1 else None)
    assert totp.verify(RFC_SECRET, value, 100 + offset, 3000) is None


@pytest.mark.parametrize("secret", ["!bad", "", "ABC", None])
def test_bad_base32(secret):
    assert totp.verify(secret, "123456", None, 3000) is None


def test_secret_and_uri():
    secret = totp.secret_new()
    assert len(base64.b32decode(secret)) == 20 and secret != totp.secret_new()
    assert totp.uri(secret, "a+b@example.test") == f"otpauth://totp/FastAccounts:a%2Bb%40example.test?secret={secret}&issuer=FastAccounts"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("FASTACCOUNTS_DB", str(tmp_path / "mfa.sqlite"))
    monkeypatch.setenv("FASTACCOUNTS_PUBLIC_URL", "https://testserver")
    for key in ("GOOGLE_ALLOWED_DOMAINS", "GOOGLE_ALLOWED_EMAILS"):
        monkeypatch.delenv(key, raising=False)
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    OrganisationService(db).create(name="Synthetic MFA OÜ", country_code="EE", entity_type="EE_OU", owner_email=EMAIL)
    with db.transaction() as tx:
        tx.execute("INSERT INTO user_accounts(id,email,name,password_hash,email_verified,created_at,updated_at) "
                   "VALUES ('mfa-owner',?,'Synthetic Owner',?,1,'2026-10-12','2026-10-12')", (EMAIL, hash_password(PASSWORD)))
    clock = [3000]
    monkeypatch.setattr(account_auth.time, "time", lambda: clock[0])
    from web_app import app
    with TestClient(app, base_url="https://testserver") as client:
        yield db, client, clock
    database.reset_database_cache()


def post(client, action, data=None, page="/mfa"):
    html = client.get(page).text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    token = re.search(r'name="token" value="([^"]+)"', html)
    return client.post(action, data={"csrf_token": csrf, **({"token": token[1]} if token else {}), **(data or {})}, follow_redirects=False)


def login(client, next_path=""):
    return post(client, "/auth/local/login", {"email": EMAIL, "password": PASSWORD, "next": next_path}, "/login")


def enable(client):
    assert login(client).status_code == 303
    response = post(client, "/auth/mfa/enroll", {"password": PASSWORD})
    secret = accounts.get(EMAIL)["totp_secret"]
    assert secret in response.text and "otpauth://" in response.text
    response = post(client, "/auth/mfa/activate", {"code": totp.code(secret, 100)})
    codes = re.findall(r'<li class="mfa-recovery-code">\s*<code>([a-f0-9]+)</code>\s*</li>', response.text)
    assert len(codes) == 10 and len(set(codes)) == 10, response.text
    assert all(c not in client.get("/mfa").text for c in codes)
    return secret, codes


def session(client):
    cookie = client.cookies.get("session_")
    return json.loads(base64.b64decode(cookie.split(".")[0]))


def test_full_lifecycle(env):
    db, client, clock = env
    assert client.get("/mfa", follow_redirects=False).headers["location"] == "/login"
    login(client)
    assert post(client, "/auth/mfa/enroll", {"password": "wrong"}).status_code == 401
    assert accounts.get(EMAIL)["totp_secret"] is None
    assert post(client, "/auth/mfa/enroll", {"password": PASSWORD}).status_code == 200
    assert post(client, "/auth/mfa/activate", {"code": "bad"}).status_code == 400
    # Start again after proving the password.
    assert post(client, "/auth/mfa/enroll", {"password": PASSWORD, "regenerate": "1"}).status_code == 200
    secret = accounts.get(EMAIL)["totp_secret"]
    response = post(client, "/auth/mfa/activate", {"code": totp.code(secret, 100)})
    codes = re.findall(r'<li class="mfa-recovery-code">\s*<code>([a-f0-9]+)</code>\s*</li>', response.text)
    assert len(codes) == 10, response.text
    assert not any(value in client.get("/mfa").text for value in codes)
    assert not any(value in json.dumps(db.rows("SELECT * FROM mfa_recovery_codes")) for value in codes)
    assert accounts.get(EMAIL)["session_version"] == 1
    client.get("/logout")
    assert login(client).headers["location"] == "/mfa"
    assert "user" not in session(client)
    assert client.get("/app", follow_redirects=False).status_code == 303
    assert post(client, "/auth/mfa/challenge", {"code": "bad"}).status_code == 401
    assert post(client, "/auth/mfa/challenge", {"code": totp.code(secret, 100)}).status_code == 401
    clock[0] += 30
    response = post(client, "/auth/mfa/challenge", {"code": totp.code(secret, 101)})
    assert response.headers["location"] == "/app"
    assert session(client)["user"]["auth"] == "password+totp"
    assert "mfa_pending" not in session(client) and client.get("/app").status_code == 200
    assert post(client, "/auth/mfa/disable", {"password": "wrong", "code": codes[0]}).status_code == 401
    assert accounts.get(EMAIL)["totp_enabled"] == 1
    assert db.scalar("SELECT used_at FROM mfa_recovery_codes WHERE code_hash=?", (token_digest(codes[0]),)) is None
    clock[0] += 30
    assert post(client, "/auth/mfa/disable", {"password": PASSWORD, "code": totp.code(secret, 102)}).status_code == 200
    assert accounts.get(EMAIL)["totp_secret"] is None and accounts.get(EMAIL)["totp_enabled"] == 0
    assert not db.rows("SELECT * FROM mfa_recovery_codes WHERE used_at IS NULL")
    client.get("/logout")
    assert login(client).headers["location"] == "/app"


def test_recovery_burn_and_regeneration(env):
    db, client, clock = env
    secret, codes = enable(client)
    client.get("/logout")
    login(client, "/app?from=mfa")
    assert post(client, "/auth/mfa/challenge", {"code": codes[0]}).headers["location"] == "/app?from=mfa"
    assert db.scalar("SELECT used_at FROM mfa_recovery_codes WHERE code_hash=?", (token_digest(codes[0]),)) == 3000
    assert post(client, "/auth/mfa/codes", {"password": PASSWORD, "code": codes[0]}).status_code == 400
    response = post(client, "/auth/mfa/codes", {"password": PASSWORD, "code": codes[1]})
    assert response.text.count('class="mfa-recovery-code"') == 10
    assert db.scalar("SELECT COUNT(*) FROM mfa_recovery_codes WHERE used_at IS NULL") == 10
    assert not accounts.challenge(EMAIL, codes[2])
    client.get("/logout")
    login(client)
    assert post(client, "/auth/mfa/challenge", {"code": codes[0]}).status_code == 401


def test_google_callback_offline(env, monkeypatch):
    _, client, clock = env
    secret, codes = enable(client)
    client.get("/logout")
    from web import google_auth
    monkeypatch.setattr(google_auth, "enabled", lambda: True)
    monkeypatch.setattr(google_auth, "authorize_url", lambda request, state: "/offline-google?state=" + state)
    monkeypatch.setattr(google_auth, "exchange", lambda request, code: {"email": EMAIL, "name": "Synthetic Owner"})
    response = client.get("/auth/google?next=/app?google=1", follow_redirects=False)
    state = response.headers["location"].split("state=")[1]
    response = client.get("/auth/google/callback", params={"state": state, "code": "offline"}, follow_redirects=False)
    assert response.headers["location"] == "/mfa" and "user" not in session(client)
    response = post(client, "/auth/mfa/challenge", {"code": codes[0]})
    assert response.headers["location"] == "/app?google=1"
    assert session(client)["user"]["auth"] == "google+totp"


@pytest.mark.parametrize("action", ["enroll", "activate", "disable", "codes", "challenge"])
def test_csrf(env, action):
    _, client, _ = env
    enable(client)
    if action == "challenge":
        client.get("/logout"); login(client)
    assert client.post("/auth/mfa/" + action, data={"code": "bad", "password": PASSWORD}).status_code == 403


@pytest.mark.parametrize("limiter", ["mfa_email", "mfa_ip"])
def test_rate_limits(env, limiter):
    _, client, _ = env
    secret, codes = enable(client)
    client.get("/logout"); login(client)
    subject = EMAIL if limiter == "mfa_email" else "testclient"
    for _ in range(account_auth.LIMITS[limiter][0]):
        accounts.hit(subject, limiter)
    assert post(client, "/auth/mfa/challenge", {"code": codes[0]}).status_code == 429
    assert "user" not in session(client)


@pytest.mark.parametrize("invalidate", ["expiry", "reset", "access"])
def test_pending_invalidation(env, monkeypatch, invalidate):
    db, client, clock = env
    _, codes = enable(client)
    client.get("/logout"); login(client)
    if invalidate == "expiry":
        clock[0] += 600
    elif invalidate == "reset":
        with db.transaction() as tx:
            tx.execute("UPDATE user_accounts SET session_version=session_version+1")
    else:
        monkeypatch.setattr("web.google_auth.access_allowed", lambda email: False)
    assert client.get("/mfa", follow_redirects=False).headers["location"] == "/login"
    assert "mfa_pending" not in session(client) and "user" not in session(client)


def test_store_guards_atomic_replay(env):
    db, client, _ = env
    secret, codes = enable(client)
    with pytest.raises(ValueError):
        accounts.enroll(EMAIL)
    for operation in (accounts.disable, accounts.codes):
        with pytest.raises(ValueError, match="error_credentials"):
            operation(EMAIL, codes[0], "wrong")
    assert db.scalar("SELECT used_at FROM mfa_recovery_codes WHERE code_hash=?", (token_digest(codes[0]),)) is None
    assert accounts.challenge(EMAIL, codes[0], session_version=2) is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(bool(x) for x in pool.map(lambda _: AccountStore(db).challenge(EMAIL, codes[0]), range(2))) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(bool(x) for x in pool.map(lambda _: AccountStore(db).challenge(EMAIL, totp.code(secret, 101)), range(2))) == 1
    assert accounts.challenge(EMAIL, totp.code(secret, 100)) is None


def test_pending_setup_requires_fresh_password(env):
    db, client, _ = env
    login(client)
    account = accounts.enroll(EMAIL)
    with pytest.raises(ValueError):
        accounts.enroll(EMAIL)
    assert account["totp_secret"] not in client.get("/mfa").text
    assert post(client, "/auth/mfa/activate", {"code": totp.code(account["totp_secret"], 100)}).status_code == 403
    assert post(client, "/auth/mfa/enroll", {"password": "wrong", "regenerate": "1"}).status_code == 401
    assert accounts.get(EMAIL)["totp_secret"] == account["totp_secret"]
    assert post(client, "/auth/mfa/enroll", {"password": PASSWORD, "regenerate": "1"}).status_code == 200
    assert accounts.get(EMAIL)["totp_secret"] != account["totp_secret"]
    with db.transaction() as tx:
        tx.execute("UPDATE user_accounts SET email_verified=0")
    with pytest.raises(ValueError):
        accounts.enroll(EMAIL, regenerate=True)


def test_challenge_token_and_safe_return(env):
    _, client, _ = env
    _, codes = enable(client)
    client.get("/logout")
    login(client, "//untrusted.example.test")
    response = post(client, "/auth/mfa/challenge", {"token": "wrong", "code": codes[0]})
    assert response.status_code == 403 and "user" not in session(client)
    csrf_before = session(client)["csrf_token"]
    response = post(client, "/auth/mfa/challenge", {"code": codes[0]})
    assert response.headers["location"] == "/app"
    assert session(client)["csrf_token"] != csrf_before
    assert codes[0] not in json.dumps(session(client))


def test_partial_migration_upgrade(env):
    db, _, _ = env
    with db.transaction() as tx:
        tx.execute("DELETE FROM schema_migrations WHERE version='0027_mfa'")
        tx.execute("DROP TABLE mfa_recovery_codes")
        tx.execute("ALTER TABLE user_accounts DROP COLUMN totp_enabled")
        tx.execute("ALTER TABLE user_accounts DROP COLUMN totp_last_step")
    assert db.migrate() == ['0027_mfa']
    assert accounts.get(EMAIL)["totp_enabled"] == 0
    assert db.scalar("SELECT COUNT(*) FROM mfa_recovery_codes") == 0


@pytest.mark.parametrize("lang", ["en", "et", "lt", "lv"])
def test_offline_browser_enrolment(env, monkeypatch, lang):
    from urllib.parse import urlsplit
    playwright = pytest.importorskip("playwright.sync_api")
    _, client, _ = env
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", lang)
    login(client)
    words = i18n.catalog(lang)["auth"]
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request_route):
            request = request_route.request
            url = urlsplit(request.url)
            if url.netloc != "testserver":
                return request_route.fulfill(status=404)
            if url.path.startswith("/static/"):
                path = ROOT / url.path.lstrip("/")
                return request_route.fulfill(path=str(path)) if path.is_file() else request_route.fulfill(status=404)
            response = client.request(request.method, url.path + ("?" + url.query if url.query else ""),
                content=request.post_data_buffer,
                headers={"Content-Type": request.headers.get("content-type", "application/x-www-form-urlencoded")},
                follow_redirects=False)
            request_route.fulfill(status=response.status_code, body=response.content,
                                 headers={"Content-Type": response.headers.get("content-type", "text/html")})

        page.route("**/*", route)
        page.goto("https://testserver/mfa")
        playwright.expect(page.locator("h1")).to_have_text(words["mfa_title"])
        page.locator('[name="password"]').fill(PASSWORD)
        page.get_by_role("button", name=words["mfa_enroll"], exact=True).click()
        playwright.expect(page.locator("#mfa-secret")).to_be_visible()
        secret = accounts.get(EMAIL)["totp_secret"]
        playwright.expect(page.locator("#mfa-secret")).to_have_value(secret)
        page.locator('[name="code"]').fill(totp.code(secret, 100))
        page.get_by_role("button", name=words["mfa_activate"], exact=True).click()
        playwright.expect(page.locator(".mfa-recovery-code")).to_have_count(10)
        page.get_by_role("link", name=words["mfa_acknowledge"]).click()
        playwright.expect(page.locator(".mfa-recovery-code")).to_have_count(0)
        assert page.locator(".auth-card").evaluate("el => el.scrollWidth <= el.clientWidth")
        assert not errors
        browser.close()


def test_migration_rerun_preserves_data(env):
    db, client, _ = env
    secret, codes = enable(client)
    original = db.rows("SELECT * FROM mfa_recovery_codes")
    assert db.scalar("SELECT COUNT(*) FROM schema_migrations") == len(catalogue())
    for _ in range(2):
        with db.transaction() as tx:
            tx.execute("DELETE FROM schema_migrations WHERE version='0027_mfa'")
        assert db.migrate() == ['0027_mfa']
    assert accounts.get(EMAIL)["totp_secret"] == secret
    assert db.rows("SELECT * FROM mfa_recovery_codes") == original
    assert f'"{catalogue()[-1]}"]' in (ROOT / ".github/workflows/ci.yml").read_text()


@pytest.mark.parametrize("lang", ["en", "et", "lt", "lv"])
def test_locales_and_workspace(lang):
    raw = json.loads((i18n.LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    english = json.loads((i18n.LOCALES_DIR / "en.json").read_text(encoding="utf-8"))
    keys = {k for k in english["auth"] if k.startswith("mfa_")}
    assert len(keys) == 22
    assert keys == {k for k in raw["auth"] if k.startswith("mfa_")}
    assert list(raw)[-(8):] == ["invoice_exports", "bulk_sending", "reminder_rules", "fx_rates", "document_settings", "copilot", "periods", "payroll_corrections"]
    for key in keys:
        assert i18n.t("auth." + key, lang) == raw["auth"][key] and "\u2014" not in raw["auth"][key]
    from web.public import workspace_page
    from fasthtml.common import to_xml
    html = to_xml(workspace_page({"email": EMAIL}, lang))
    assert 'href="/mfa"' in html and raw["workspace"]["Two-factor authentication"] in html
