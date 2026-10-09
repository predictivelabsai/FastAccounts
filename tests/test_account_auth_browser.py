"""Playwright: register, confirm, sign out, reset and sign in again (English and Estonian)."""
from __future__ import annotations

import re
import socket
import threading
import time

import pytest


@pytest.fixture
def live(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    import uvicorn
    import database
    from organisations import OrganisationService
    from web import account_auth
    from web_app import app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://localhost:{port}"
    monkeypatch.setenv("FASTACCOUNTS_DB", str(tmp_path / "browser-auth.sqlite"))
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("FASTACCOUNTS_PUBLIC_URL", base)
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    for lang in ("en", "et"):
        OrganisationService(db).create(name=f"Browser {lang} OÜ", country_code="EE", entity_type="EE_OU",
                                       owner_email=f"owner-{lang}@example.test")
    mails: list[str] = []
    monkeypatch.setattr(account_auth, "send_email", lambda to, subject, html, text: mails.append(text) or True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        yield playwright, base, mails
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        database.reset_database_cache()


def _link(mails, purpose):
    return re.findall(rf"(http://localhost:\d+/auth/local/{purpose}/[A-Za-z0-9_\-]+)", mails[-1])[-1]


@pytest.mark.parametrize("lang", ["en", "et"])
def test_email_account_lifecycle_in_browser(live, lang):
    playwright, base, mails = live
    from web import i18n
    T = lambda key: i18n.t(f"auth.{key}", lang)
    email, first, second = f"owner-{lang}@example.test", "first password 123", "second password 456"
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page()
        page.goto(f"{base}/set-lang/{lang}?next=/login")
        expect = playwright.expect
        expect(page.locator('a[href="/auth/google"]')).to_be_visible()
        expect(page.locator("#auth-login-form")).to_be_visible()

        page.get_by_role("link", name=T("tab_register")).click()
        page.fill("#auth-register-name", "Browser Owner")
        page.fill("#auth-register-email", email)
        page.fill("#auth-register-password", first)
        page.get_by_role("button", name=T("submit_register")).click()
        expect(page.locator(".auth-notice")).to_have_text(T("notice_registered"))

        page.goto(_link(mails, "verify"))
        expect(page.locator("h1")).to_have_text(T("verify_title"))
        page.fill("#auth-verify-password", first)
        page.get_by_role("button", name=T("submit_verify")).click()
        page.wait_for_url(f"{base}/app")
        expect(page.locator("#workspace-app")).to_be_visible()

        page.goto(f"{base}/logout")
        page.goto(f"{base}/login")
        page.get_by_role("link", name=T("forgot_link")).click()
        page.fill("#auth-forgot-email", email)
        page.get_by_role("button", name=T("submit_forgot")).click()
        expect(page.locator(".auth-notice")).to_have_text(T("notice_reset_sent"))

        page.goto(_link(mails, "reset"))
        expect(page.locator("h1")).to_have_text(T("reset_title"))
        page.fill("#auth-reset-password", second)
        page.get_by_role("button", name=T("submit_reset")).click()
        page.wait_for_url(re.compile(r".*/login\?notice=password_reset$"))
        expect(page.locator(".auth-notice")).to_have_text(T("notice_password_reset"))

        page.fill("#auth-login-email", email)
        page.fill("#auth-login-password", first)
        page.get_by_role("button", name=T("submit_signin")).click()
        expect(page.locator(".error")).to_have_text(T("error_credentials"))
        page.fill("#auth-login-password", second)
        page.get_by_role("button", name=T("submit_signin")).click()
        page.wait_for_url(f"{base}/app")
        expect(page.locator("#workspace-app")).to_be_visible()
        browser.close()
