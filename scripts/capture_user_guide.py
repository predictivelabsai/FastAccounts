"""Capture user-guide screenshots (en + et) from an isolated, seeded local instance.

Adapted from FastShop's scripts/capture_user_guide.py (itself following FastClinic):
a disposable SQLite database, the in-process app on a local port, external
requests blocked, a fixed 1440x900 viewport and no saved browser session.
The same walk-through doubles as a click-through regression of every workspace
area: it fails on any browser page error or failed /api call.

Run (Chrome + Playwright from the dev setup; see docs/USER_GUIDE_BUILD.md):

    .venv/bin/python -m scripts.capture_user_guide

Each language runs in a child process on its own /tmp/fastaccounts-guide-* database.

Only synthetic data is shown: the seeded demo books, "Demo OÜ (sample payroll)"
with test personal codes, and a mocked FastHR API (no network calls).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 5047
BASE = f"http://127.0.0.1:{PORT}"
OUT = ROOT / "screenshots"
VIEWPORT = {"width": 1440, "height": 1000}
LANGUAGES = ("en", "et")
FASTHR_ROWS = [  # Synthetic FastHR employee API rows (annual base_salary, as in FastHR).
    {"id": 501, "code": "FH-501", "first_name": "Kadri", "last_name": "Saar", "status": "Active",
     "email": "kadri.saar@demo-ou.example", "designation": "Senior accountant", "base_salary": 45600,
     "working_time_ratio": 1.0, "branch": "Tallinn"},
    {"id": 502, "code": "FH-502", "first_name": "Eva", "last_name": "Näidis", "status": "Active",
     "email": "eva.naidis@demo-ou.example", "designation": "Payroll assistant", "base_salary": 14400,
     "working_time_ratio": 0.6, "branch": "Tartu"},
    {"id": 503, "code": "FH-503", "first_name": "Rein", "last_name": "Proov", "status": "Active",
     "email": "rein.proov@demo-ou.example", "designation": "Warehouse", "base_salary": 0,
     "hourly_rate": 7.5, "working_time_ratio": 1.0, "branch": "Tallinn"},
    {"id": 504, "code": "FH-504", "first_name": "Uku", "last_name": "Test", "status": "Active",
     "email": "uku.test@demo-ou.example", "designation": "Intern", "base_salary": None,
     "working_time_ratio": 1.0, "branch": "Tartu"},
]

EMPLOYEE_CSV = (  # Synthetic export as a payroll/HR system would produce it (monthly salary).
    "Employee ID,Name,Email,Salary,Status\n"
    "CSV-101,Mari Näidis,mari.naidis@demo-ou.example,1650.00,Active\n"
    "CSV-102,Karl Proovikivi,karl.proovikivi@demo-ou.example,2100.00,Active\n"
)


def _guard() -> None:
    db = os.getenv("FASTACCOUNTS_DB", "")
    if os.getenv("DB_URL") or not db.startswith("/tmp/fastaccounts-guide-"):
        raise SystemExit("Use an isolated FASTACCOUNTS_DB=/tmp/fastaccounts-guide-*/… and an empty DB_URL.")
    os.environ.update(FASTACCOUNTS_ALLOW_TEST_AUTH="true", FASTACCOUNTS_ENV="development",
                      FASTACCOUNTS_DEFAULT_LANG="en", FASTACCOUNTS_PUBLIC_URL=BASE)
    if not os.getenv("FASTACCOUNTS_ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet
        os.environ["FASTACCOUNTS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()  # in-memory only


def _mock_fasthr() -> None:
    """Route the FastHR connector to an in-process mock of its employee API."""
    from dataclasses import replace
    import httpx
    from connectors.providers import FastHRProvider
    from connectors.registry import REGISTRY

    def handler(request):
        return httpx.Response(200, json={"data": FASTHR_ROWS,
                                         "meta": {"total": len(FASTHR_ROWS), "limit": 200, "offset": 0}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    REGISTRY["fasthr"] = replace(REGISTRY["fasthr"], factory=lambda credentials, config: FastHRProvider(
        base_url=credentials.get("base_url") or FastHRProvider.default_base_url,
        token=credentials["token"], client=client))


def _seed() -> dict:
    from database import get_database
    from integration_service import IntegrationService
    from seed import DEMO_EMAIL, SAMPLE_PAYROLL_ORG, seed_demo
    uk, ee = seed_demo()
    db = get_database()
    sample = db.one("SELECT * FROM organisations WHERE name=?", (SAMPLE_PAYROLL_ORG,))
    integration = IntegrationService(db)
    integration.configure(sample["id"], "fasthr", actor=DEMO_EMAIL, config={},
                          credentials={"base_url": "https://fasthr.example.test", "token": "synthetic-guide-token"})
    integration.test_connection(sample["id"], "fasthr", actor=DEMO_EMAIL, config={},
                                credentials={"base_url": "https://fasthr.example.test", "token": "synthetic-guide-token"})
    return {"uk": uk["id"], "ee": ee["id"], "sample": sample["id"]}


MAILS: list[str] = []


def _serve():
    import uvicorn
    from web import account_auth
    from web_app import app
    # Account emails (reset links) are kept in memory; nothing is sent.
    account_auth.send_email = lambda to, subject, html, text: MAILS.append(text) or True
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline:
        time.sleep(.1)
    if not server.started:
        raise RuntimeError("Local capture server did not start")
    return server, thread


def _pdf_page_png(pdf: bytes, target: Path, *, contains: str) -> None:
    """Render the PDF page (one payslip per page) that mentions `contains` to PNG."""
    with tempfile.TemporaryDirectory(prefix="fastaccounts-guide-pdf-") as tmp:
        source = Path(tmp) / "doc.pdf"
        source.write_bytes(pdf)
        text = subprocess.check_output(["pdftotext", "-layout", str(source), "-"], text=True)
        number = next(i for i, chunk in enumerate(text.split("\f"), 1) if contains in chunk)
        subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", str(number), "-l", str(number), "-singlefile",
                        str(source), str(target.with_suffix(""))], check=True)


def capture_language(browser, lang: str, orgs: dict) -> list[str]:
    import re
    from playwright.sync_api import expect
    out = OUT / lang
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    errors: list[str] = []
    context = browser.new_context(viewport=VIEWPORT, reduced_motion="reduce",
                                  locale="et-EE" if lang == "et" else "en-GB", timezone_id="Europe/Tallinn")
    context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(BASE + "/") else route.abort())
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on("response", lambda r: errors.append(f"{r.status} {r.url}")
            if "/api/" in r.url and r.status >= 400 else None)
    shots: list[str] = []
    counter = iter(range(1, 100))

    def settle():
        page.wait_for_load_state("networkidle")
        expect(page.locator("#app-content .skeleton")).to_have_count(0)
        expect(page.locator("#toasts .toast")).to_have_count(0, timeout=15000)
        page.evaluate("document.fonts.ready")

    def capture(name):
        settle()
        page.evaluate("document.activeElement && document.activeElement.blur && document.activeElement.blur()")
        page.mouse.move(VIEWPORT["width"] - 5, VIEWPORT["height"] - 5)
        file = f"{next(counter):02d}-{name}"
        page.screenshot(path=str(out / f"{file}.png"))
        shots.append(file)

    def view(hash_):
        page.evaluate(f"location.hash = {hash_!r}")
        page.wait_for_timeout(150)
        settle()

    def switch(oid):
        page.locator("#org-trigger").click()
        page.locator(f'[data-org="{oid}"]').click()
        settle()

    def dialog():
        expect(page.locator(".dialog")).to_be_visible()
        return page.locator(".dialog")

    def close_dialog():
        page.keyboard.press("Escape")
        expect(page.locator(".dialog")).to_have_count(0)

    def confirm():
        page.locator('.dialog [data-action="confirm"]').click()
        expect(page.locator(".dialog")).to_have_count(0)
        expect(page.locator("#toasts .toast")).not_to_have_count(0)

    # Public site and sign-in, then switch the workspace language from its top bar.
    page.goto(f"{BASE}/set-lang/{lang}?next=/")
    capture("public-home")
    page.goto(f"{BASE}/login")
    capture("sign-in")
    page.goto(f"{BASE}/auth/test")
    page.locator(f'.workspace-languages a[lang="{lang}"]').click()
    expect(page.locator("#workspace-app")).to_have_attribute("data-lang", lang)

    # Bureau overview and client (organisation) switching.
    switch(orgs["ee"])
    view("overview")
    capture("overview")
    page.locator("#org-trigger").click()
    expect(page.locator("#org-menu")).to_be_visible()
    capture("organisation-switcher")
    page.keyboard.press("Escape")

    # Sales and purchase documents.
    view("invoices")
    capture("invoices")
    page.locator('[data-action="newInvoice"]').first.click()
    dialog()
    capture("new-invoice")
    close_dialog()
    view("bills")
    capture("bills")
    view("contacts")
    capture("contacts")

    # Recurring invoices and the reminder ladder (seeded on the UK demo books).
    switch(orgs["uk"])
    view("recurring")
    capture("recurring-reminders")
    page.locator('[data-action="newSchedule"]').first.click()
    dialog()
    capture("new-schedule")
    close_dialog()

    # Banking, accounting reports and tax workpapers (Estonian books).
    switch(orgs["ee"])
    view("banking")
    capture("banking")
    view("accounting")
    capture("accounting-trial-balance")
    view("tax")
    capture("tax-kmd")

    # Payroll for a bureau client: Demo OÜ (sample payroll).
    switch(orgs["sample"])
    view("payroll")
    capture("payroll-employees")
    rows = page.locator("#app-content table").first.locator("tbody tr")
    rows.filter(has_text="Liis Kuusk").locator('[data-action="edit"]').click()
    dialog()
    capture("employee-part-time")
    close_dialog()
    rows.filter(has_text="Peeter Oja").locator('[data-action="edit"]').click()
    expect(page.locator(".dialog [name=hourly_rate]")).to_be_visible()
    capture("employee-hourly")
    close_dialog()
    page.locator(".run-detail details[open]").first.scroll_into_view_if_needed()
    capture("pay-run-draft-breakdown")
    # A new month: the wizard asks for hours of hourly staff.
    page.locator('[data-action="run"]').first.click()
    wizard = dialog()
    wizard.locator("[name=period]").fill("2026-11")
    for hours in wizard.locator('input[name^="hours:"]').all():
        hours.fill("160")
    capture("pay-run-wizard")
    wizard.locator('[type="submit"], [data-action="save"]').last.click()
    expect(page.locator('.dialog [data-action="confirm"]')).to_be_visible()
    confirm()
    settle()
    # Approve and post the October draft to the ledger.
    page.locator("#app-content tr").filter(has_text="2026-10").locator('[data-action="approve"]').click()
    dialog()
    capture("pay-run-approve")
    confirm()
    settle()
    october = page.locator("#app-content tr").filter(has_text="2026-10").locator('a[href$="/payslips.pdf"]')
    pdf = page.request.get(BASE + october.get_attribute("href"))
    assert pdf.ok and pdf.body().startswith(b"%PDF")
    file = f"{next(counter):02d}-payslip-pdf"
    _pdf_page_png(pdf.body(), out / f"{file}.png", contains="Liis Kuusk")
    shots.append(file)
    view("accounting")
    page.locator('[data-report="general-ledger"]').click()
    settle()
    capture("payroll-general-ledger")

    # Integrations and the reviewed FastHR employee import.
    view("integrations")
    capture("integrations")
    page.locator('[data-action="configureIntegration"][data-provider="fasthr"]').click()
    dialog()
    capture("fasthr-configure")
    close_dialog()
    page.locator('[data-action="runEmployeeImport"][data-provider="fasthr"]').click()
    expect(page).to_have_url(re.compile(r"#integrations/review/fasthr/"))
    capture("fasthr-import-review")
    for box in page.locator('[data-decision="apply"]').all():
        box.check()
    page.locator('[data-action="applyImportDecisions"]').first.click()
    expect(page.locator(".notice, .outcome-summary").first).to_be_visible()
    capture("fasthr-import-applied")
    # Universal employee file import (CSV/TSV export from any payroll or HR system).
    view("integrations")
    page.locator('[data-action="importEmployeeFile"][data-provider="file_import"]').click()
    upload = dialog()
    upload.locator("[name=csv_content]").fill(EMPLOYEE_CSV)
    capture("file-import-dialog")
    upload.locator('button[type="submit"]').click()
    expect(page).to_have_url(re.compile(r"#integrations/review/file_import/"))
    capture("file-import-review")
    view("payroll")
    expect(page.locator("#app-content")).to_contain_text("Eva Näidis")
    capture("payroll-after-import")

    # Email and password accounts beside Google sign-in; reset links stay in memory.
    page.goto(f"{BASE}/logout")
    page.goto(f"{BASE}/login?tab=register")
    page.fill("#auth-register-name", "Mari Näidis")
    page.fill("#auth-register-email", "mari.naidis@example.test")
    capture("create-account")
    page.goto(f"{BASE}/login?tab=forgot")
    page.fill("#auth-forgot-email", "demo@fastaccounts.local")
    page.locator('#auth-forgot-form button[type="submit"]').click()
    expect(page.locator(".auth-notice")).to_be_visible()
    capture("forgot-password")
    link = re.findall(rf"{re.escape(BASE)}/auth/local/reset/[A-Za-z0-9_\-]+", MAILS[-1])[-1]
    page.goto(link)
    expect(page.locator("#auth-reset-form")).to_be_visible()
    capture("reset-password")

    context.close()
    if errors:
        raise AssertionError(f"{lang}: " + "; ".join(errors))
    return shots


def main() -> None:
    lang = os.getenv("GUIDE_LANG")
    if lang is None:  # Re-run once per language, each on its own fresh database.
        results = {}
        for code in LANGUAGES:
            with tempfile.TemporaryDirectory(prefix="fastaccounts-guide-") as tmp:
                env = os.environ | {"GUIDE_LANG": code, "FASTACCOUNTS_DB": f"{tmp}/guide.sqlite", "DB_URL": ""}
                subprocess.run([sys.executable, "-m", "scripts.capture_user_guide"], cwd=ROOT, env=env, check=True)
            results[code] = len(list((OUT / code).glob("*.png")))
        print({"status": "passed", "captures": results, "output": str(OUT.relative_to(ROOT))})
        return
    _guard()
    _mock_fasthr()
    orgs = _seed()
    server, thread = _serve()
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as pw:
            # Chrome formats date inputs from its UI language, so set it per guide language.
            locale = "et-EE" if lang == "et" else "en-GB"
            browser = pw.chromium.launch(channel=os.getenv("GUIDE_BROWSER_CHANNEL", "chrome"), args=[f"--lang={locale}"],
                                         env=os.environ | {"LANGUAGE": locale.replace("-", "_"),
                                                           "LANG": locale.replace("-", "_") + ".UTF-8"})
            shots = capture_language(browser, lang, orgs)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    print({"language": lang, "captures": len(shots)})


if __name__ == "__main__":
    main()
