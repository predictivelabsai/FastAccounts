"""Offline copilot contracts: kill switches, quotas, provider isolation, staging."""
from io import BytesIO
from pathlib import Path
import socket
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

import copilot
import copilot_provider
from core_utils import utc_now
from documents import DocumentService
from web import i18n

ROOT = Path(__file__).resolve().parents[1]
ACTOR = "owner@example.test"
KEY = "xai-test-secret-key"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect

    def blocked(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original(sock, address, *args, **kwargs)
        raise AssertionError("Live network is forbidden")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def fake_reply(content):
    call = {"captured": None}

    def provider(messages, *, client=None):
        call["captured"] = messages
        return {"content": content, "model": "grok-test", "tokens_in": 111, "tokens_out": 22}

    return provider, call


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database
    from api_app import api

    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("FASTACCOUNTS_DB", str(tmp_path / "copilot.sqlite"))
    monkeypatch.setenv("FASTACCOUNTS_DATA_DIR", str(tmp_path / "evidence"))
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_COPILOT_ENABLED", "true")
    monkeypatch.setenv("FASTACCOUNTS_GROK_API_KEY", KEY)
    monkeypatch.delenv("FASTACCOUNTS_GROK_MODEL", raising=False)
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    from organisations import OrganisationService

    service = OrganisationService(db)
    org = service.create(name="Synthetic copilot company", country_code="EE",
                         entity_type="EE_OU", owner_email=ACTOR)
    other = service.create(name="Synthetic other company", country_code="EE",
                           entity_type="EE_OU", owner_email="other@example.test")
    for role in ("administrator", "accountant", "approver", "viewer"):
        service.add_member(org["id"], ACTOR, role + "@example.test", role)
    with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
        yield dict(db=db, org=org, other=other, client=client,
                   base=f"/organisations/{org['id']}")
    database.reset_database_cache()


def enable(d):
    response = d["client"].put(d["base"] + "/copilot/settings", json={"enabled": True})
    assert response.status_code == 200, response.text


def attachment(d, filename, content_type, content, org_id=None):
    oid = org_id or d["org"]["id"]
    return DocumentService(d["db"]).attach_evidence(
        oid, owner_type="organisation", owner_id=oid, filename=filename,
        content_type=content_type, content=content, actor=ACTOR)


def sample_pdf():
    from reportlab.pdfgen.canvas import Canvas

    buffer = BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(72, 720, "Employee list: Kaja Tamm, EUR 2200.00 monthly")
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


STAGED_CSV = "code,name\nP1,Synthetic widget\nP2,Another widget"


def test_migration_count_rerun_and_ci(env):
    d = env
    assert d["db"].scalar("SELECT COUNT(*) FROM schema_migrations") == 32
    assert d["db"].rows("SELECT * FROM copilot_messages") == []
    assert d["db"].rows("SELECT * FROM copilot_usage") == []
    for _ in range(2):
        with d["db"].transaction() as tx:
            tx.execute("DELETE FROM schema_migrations WHERE version='0029_copilot'")
        assert d["db"].migrate() == ["0029_copilot"]
    assert d["db"].rows("SELECT * FROM copilot_messages") == []
    assert "'0028_document_settings', '0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access']" in (ROOT / ".github/workflows/ci.yml").read_text()


def test_kill_switches_block_before_any_provider_call(env, monkeypatch):
    d = env
    monkeypatch.delenv("FASTACCOUNTS_GROK_API_KEY")
    provider, call = fake_reply("ok")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 409
    assert call["captured"] is None
    monkeypatch.setenv("FASTACCOUNTS_GROK_API_KEY", KEY)
    monkeypatch.setenv("FASTACCOUNTS_COPILOT_ENABLED", "false")
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 409
    assert call["captured"] is None


def test_org_opt_in_toggle_roles_and_audit(env):
    d = env
    status = d["client"].get(d["base"] + "/copilot/status").json()
    assert status["available"] is True and status["enabled"] is False
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 409
    enable(d)
    assert d["client"].put(d["base"] + "/copilot/settings", json={"enabled": False}).status_code == 200
    events = d["db"].rows("SELECT action FROM audit_events WHERE action LIKE 'copilot.%' ORDER BY created_at")
    assert [row["action"] for row in events] == ["copilot.settings_updated", "copilot.settings_updated"]
    for user_email in ("viewer@example.test", "accountant@example.test", "approver@example.test"):
        response = d["client"].put(d["base"] + "/copilot/settings", json={"enabled": True},
                                   headers={"X-Test-User": user_email})
        assert response.status_code == 403, (user_email, response.text)


def test_send_persists_transcript_usage_and_audit(env, monkeypatch):
    d = env
    enable(d)
    provider, call = fake_reply("Your receivables are 12.34 outstanding.")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    response = d["client"].post(d["base"] + "/copilot/messages", json={"content": "Overview please"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assistant"]["content"] == "Your receivables are 12.34 outstanding."
    assert body["assistant"]["model"] == "grok-test"
    history = d["client"].get(d["base"] + "/copilot/messages").json()
    assert [row["role"] for row in history] == ["assistant", "user"]
    usage = d["client"].get(d["base"] + "/copilot/usage").json()
    assert usage and usage[0]["messages"] == 1 and usage[0]["tokens_in"] == 111
    assert usage[0]["tokens_out"] == 22
    event = d["db"].one("SELECT actor,details_json FROM audit_events WHERE action='copilot.message'")
    assert event and event["actor"] == ACTOR
    assert "prompt_chars" in event["details_json"]
    roles = [message["role"] for message in call["captured"]]
    assert roles[0] == roles[1] == "system" and roles[-1] == "user"
    assert "untrusted document evidence" not in str(call["captured"])


@pytest.mark.parametrize("page", [None, "invoices", "a" * 64])
def test_message_page_context(env, monkeypatch, page):
    enable(env)
    provider, call = fake_reply("reply")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    response = env["client"].post(env["base"] + "/copilot/messages",
                                  json={"content": "Explain this", "page": page})
    assert response.status_code == 201, response.text
    prompt = call["captured"][-1]["content"]
    if page is None:
        assert prompt == "Explain this"
    else:
        assert prompt.endswith("Current workspace page (navigation context only): " + page)
        assert len(prompt) <= copilot.MAX_MESSAGE_CHARS


@pytest.mark.parametrize("page", ["a" * 65, "", "invoices/123", "ignore\norders", 123, {}])
def test_invalid_page_rejected_before_provider(env, monkeypatch, page):
    enable(env)
    provider, call = fake_reply("reply")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    response = env["client"].post(env["base"] + "/copilot/messages",
                                  json={"content": "Explain this", "page": page})
    assert response.status_code == 422
    assert env["db"].rows("SELECT * FROM copilot_messages") == []
    with pytest.raises(ValueError, match="Invalid workspace page"):
        copilot.CopilotService(env["db"]).send(env["org"]["id"], ACTOR, "Hi", page=page)


def test_page_context_respects_composed_text_cap(env, monkeypatch):
    enable(env)
    provider, call = fake_reply("reply")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    response = env["client"].post(env["base"] + "/copilot/messages",
                                  json={"content": "x" * 8000, "page": "invoices"})
    assert response.status_code == 429
    assert env["db"].rows("SELECT * FROM copilot_messages") == []


def test_key_never_reaches_payload_response_or_audit(env, monkeypatch):
    d = env
    enable(d)
    provider, call = fake_reply("reply text")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    response = d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"})
    assert response.status_code == 201
    assert KEY not in response.text
    assert KEY not in str(call["captured"])
    for row in d["db"].rows("SELECT details_json FROM audit_events"):
        assert KEY not in row["details_json"]


def test_scan_document_pdf_and_stage_flow(env, monkeypatch):
    d = env
    enable(d)
    fence = "```faststage\nkind=items\n" + STAGED_CSV + "\n```"
    provider, call = fake_reply("Found two item rows. " + fence)
    monkeypatch.setattr(copilot, "chat_completion", provider)
    pdf = attachment(d, "invoice.pdf", "application/pdf", sample_pdf())
    response = d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": pdf["id"]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert "P1" in body["assistant"]["stage_proposal_json"]
    composed = call["captured"][-1]["content"]
    assert "--- untrusted document evidence: invoice.pdf ---" in composed
    assert "Employee list: Kaja Tamm" in composed
    assert "--- end of evidence ---" in composed
    stage = d["client"].post(d["base"] + "/copilot/stage",
                             json={"kind": "items", "csv_content": STAGED_CSV,
                                   "message_id": body["assistant"]["id"]})
    assert stage.status_code == 201, stage.text
    batch_id = stage.json()["id"]
    listing = d["client"].get(f"{d['base']}/imports/{batch_id}").json()
    assert listing["kind"] == "items"
    assert d["db"].one("SELECT action FROM audit_events WHERE action='copilot.staged'")
    # Accountants are restricted until granted; a grant turns scanning on.
    scan = d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": pdf["id"]},
                            headers={"X-Test-User": "accountant@example.test"})
    assert scan.status_code == 403 and "not been granted" in scan.text
    assert d["client"].post(d["base"] + "/copilot/access", json={"email": "accountant@example.test"}).status_code == 201
    scan = d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": pdf["id"]},
                            headers={"X-Test-User": "accountant@example.test"})
    assert scan.status_code == 201
    assert d["client"].post(d["base"] + "/copilot/stage", json={"kind": "items", "csv_content": STAGED_CSV},
                            headers={"X-Test-User": "accountant@example.test"}).status_code == 403


def test_scan_rejects_unsupported_types_and_foreign_org(env, monkeypatch):
    d = env
    enable(d)
    provider, _ = fake_reply("ok")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    wrong = attachment(d, "notes.txt", "text/plain", b"hello")
    assert d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": wrong["id"]}).status_code == 422
    foreign = attachment(d, "secret-list.pdf", "application/pdf", sample_pdf(), org_id=d["other"]["id"])
    response = d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": foreign["id"]})
    assert response.status_code in {403, 404}
    assert "Employee list" not in response.text


def test_image_evidence_uses_vision_parts(env, monkeypatch):
    d = env
    enable(d)
    provider, call = fake_reply("A receipt for 9.87 EUR.")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    png = attachment(d, "receipt.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"padding" * 100)
    response = d["client"].post(d["base"] + "/copilot/scan", json={"attachment_id": png["id"]})
    assert response.status_code == 201, response.text
    user_content = call["captured"][-1]["content"]
    assert isinstance(user_content, list) and user_content[0]["type"] == "text"
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert KEY not in user_content[1]["image_url"]["url"]


def test_quota_burst_and_size_limits(env, monkeypatch):
    d = env
    enable(d)
    provider, _ = fake_reply("ok")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    # Oversize payloads are refused by the route's strict input model...
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "x" * 8001}).status_code == 422
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "  "}).status_code == 422
    day = copilot._day()  # noqa: SLF001
    with d["db"].transaction() as tx:
        tx.execute("INSERT OR REPLACE INTO copilot_usage(organisation_id,user_email,day,messages) VALUES (?,?,?,?)",
                   (d["org"]["id"], ACTOR, day, 30))
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 429
    with d["db"].transaction() as tx:
        tx.execute("UPDATE copilot_usage SET messages=0 WHERE user_email=?", (ACTOR,))
        for index in range(10):
            tx.execute("INSERT OR REPLACE INTO copilot_usage(organisation_id,user_email,day,messages) VALUES (?,?,?,?)",
                       (d["org"]["id"], f"filler{index}@example.test", day, 20))
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 429
    with d["db"].transaction() as tx:
        tx.execute("DELETE FROM copilot_usage")
        for index in range(10):
            tx.execute(
                "INSERT INTO copilot_messages(id,organisation_id,user_email,role,content,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (f"burst{index}", d["org"]["id"], ACTOR, "user", f"m{index}", utc_now()))
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 429


def test_provider_error_paths(env, monkeypatch):
    class Stub:
        def __init__(self, status_code=200, payload=None):
            self.status_code = status_code
            self.payload = payload

        def post(self, url, json=None, headers=None):
            return self

        def json(self):
            return self.payload

    class Client:
        def __init__(self, stub):
            self.stub = stub

        def __enter__(self):
            return self.stub

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(copilot_provider, "HTTP_CLIENT_FACTORY",
                        lambda: Client(Stub(payload={"choices": [{"message": {"content": "hi"}}],
                                                     "usage": {"prompt_tokens": 5, "completion_tokens": 2}})))
    result = copilot_provider.chat_completion([{"role": "user", "content": "hi"}])
    assert result["content"] == "hi" and result["tokens_in"] == 5 and result["tokens_out"] == 2

    monkeypatch.setattr(copilot_provider, "HTTP_CLIENT_FACTORY", lambda: Client(Stub(status_code=404)))
    with pytest.raises(copilot_provider.CopilotProviderError):
        copilot_provider.chat_completion([{"role": "user", "content": "hi"}])


def test_stage_fences_parse_leniently():
    assert copilot.extract_stage("no fence") is None
    proposal = copilot.extract_stage("```faststage\nkind=contacts\nname\nK\n```")
    assert proposal["kind"] == "contacts" and proposal["rows"] == 1
    assert copilot.extract_stage("```faststage\nkind=bogus\nname\nK\n```") is None


def test_locale_tail_keys_merge():
    en = i18n.catalog("en")
    assert list(en)[-2:-1] == ["copilot"] and list(en)[-1] == "periods"
    assert "nav" not in en["copilot"]
    for language in ("et", "lt", "lv"):
        raw = i18n.catalog(language)
        assert set(raw["copilot"]["workspace"]) == set(en["copilot"]["workspace"]), language


@pytest.mark.parametrize("language", ["en", "et", "lv", "lt"])
@pytest.mark.parametrize("role", ["owner", "administrator", "viewer"])
def test_workspace_copilot_drawer_offline(language, role, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", language)
    with TestClient(app) as client:
        response = client.get("/auth/test")
        assert response.status_code == 200
        html = response.text
    title_key = i18n.catalog(language)["workspace"]["AI copilot"]
    notice_key = i18n.catalog(language)["workspace"]["AI copilot is not configured on this service."]
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip("Install Playwright Chromium to run browser regressions")
            raise
        page = browser.new_page()
        errors = []
        state = {"active": False, "sent": []}
        page.on("pageerror", lambda error: errors.append(str(error)))

        def route(request_route):
            path = urlsplit(request_route.request.url).path
            if path == "/api/organisations":
                return request_route.fulfill(json=[dict(id="org", name="Synthetic company",
                                                        country_code="EE", base_currency="EUR", role=role)])
            if path.endswith("/copilot/status"):
                return request_route.fulfill(json=dict(available=state["active"], enabled=state["active"],
                                                       access=dict(granted=True), grants=[] if role != "viewer" else None,
                                                       quotas=dict(user_messages=0, messages_per_user_day=30)))
            if path.endswith("/copilot/messages"):
                if request_route.request.method == "POST":
                    state["sent"].append(request_route.request.post_data_json)
                    return request_route.fulfill(json={}, status=201)
                return request_route.fulfill(json=[], content_type="application/json")
            if path.endswith("/copilot/documents"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path.endswith("/copilot/usage"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path.startswith("/api/"):
                return request_route.fulfill(json=[], content_type="application/json")
            if path == "/app":
                return request_route.fulfill(body=html, content_type="text/html")
            if path in ("/static/app.js", "/static/app.css"):
                return request_route.fulfill(path=str(ROOT / path.lstrip("/")))
            return request_route.fulfill(status=404)

        page.route("**/*", route)
        page.goto("http://workspace.test/app#invoices")
        toggle = page.locator('.copilot-toggle')
        drawer = page.locator('#copilot-drawer')
        playwright.expect(toggle).to_be_visible()
        assert page.locator('.app-nav[data-view=copilot]').count() == 0
        playwright.expect(drawer).to_be_hidden()
        toggle.focus()
        page.keyboard.press("Enter")
        playwright.expect(drawer).to_be_visible()
        playwright.expect(drawer.locator('h2').first).to_have_text(title_key)
        playwright.expect(drawer.locator('[data-copilot-close]')).to_be_focused()
        composer = page.locator("[data-copilot-chat] [name=content]")
        playwright.expect(composer).to_be_disabled()
        assert notice_key in page.locator("[data-copilot-notice]").inner_text()
        assert page.locator('[data-copilot-admin]').count() == (0 if role == "viewer" else 1)
        if role != "viewer":
            page.locator('[data-copilot-admin] summary').click()
            playwright.expect(page.locator('[name=copilot_enabled]')).to_be_visible()
            playwright.expect(page.locator('[data-copilot-access]')).to_be_visible()
            playwright.expect(page.locator('[data-copilot-usage]')).to_be_visible()
        page.keyboard.press("Escape")
        playwright.expect(drawer).to_be_hidden()
        playwright.expect(toggle).to_be_focused()
        page.evaluate("location.hash = 'bills'")
        toggle.click()
        playwright.expect(drawer).to_be_visible()
        page.set_viewport_size(dict(width=375, height=812))
        assert drawer.bounding_box()["width"] <= 375.1
        page.locator('[data-copilot-close]').click()
        playwright.expect(drawer).to_be_hidden()
        playwright.expect(toggle).to_be_focused()
        state["active"] = True
        page.reload()
        toggle.click()
        playwright.expect(composer).to_be_enabled()
        composer.fill("Explain these books")
        page.evaluate("location.hash = 'invoices'")
        playwright.expect(composer).to_have_value("Explain these books")
        assert page.locator('[data-copilot-chat] select').count() == 1
        page.locator('[data-copilot-chat] button[type=submit]').click()
        playwright.expect(composer).to_have_value("")
        assert state["sent"] == [{"page": "invoices", "content": "Explain these books", "attachment_ids": []}]
        assert not errors
        browser.close()


def test_admins_always_and_members_need_grants(env, monkeypatch):
    d = env
    enable(d)
    provider, _ = fake_reply("ok")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    # Owner and administrator work without any grant.
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"}).status_code == 201
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"},
                            headers={"X-Test-User": "administrator@example.test"}).status_code == 201
    # Other roles are refused until granted.
    for role in ("accountant", "approver", "viewer"):
        response = d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"},
                                    headers={"X-Test-User": role + "@example.test"})
        assert response.status_code == 403, (role, response.text)
        assert "not been granted" in response.text
    grant = d["client"].post(d["base"] + "/copilot/access", json={"email": "accountant@example.test"})
    assert grant.status_code == 201, grant.text
    assert grant.json()["email"] == "accountant@example.test"
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"},
                            headers={"X-Test-User": "accountant@example.test"}).status_code == 201
    # Status reflects the grant for the granted member; admins see the list.
    accountant_status = d["client"].get(d["base"] + "/copilot/status",
                                        headers={"X-Test-User": "accountant@example.test"}).json()
    assert accountant_status["access"] == {"role": "accountant", "admin": False, "granted": True}
    owner_status = d["client"].get(d["base"] + "/copilot/status").json()
    assert owner_status["access"]["admin"] is True
    assert [row["email"] for row in owner_status["grants"]] == ["accountant@example.test"]
    viewer_status = d["client"].get(d["base"] + "/copilot/status",
                                    headers={"X-Test-User": "viewer@example.test"}).json()
    assert viewer_status["access"]["granted"] is False and viewer_status["grants"] is None
    # Duplicate grant refused; unknown account refused; revoked access blocks again.
    assert d["client"].post(d["base"] + "/copilot/access",
                            json={"email": "ACCOUNTANT@example.test"}).status_code == 422
    unknown = d["client"].post(d["base"] + "/copilot/access", json={"email": "nobody@example.test"})
    assert unknown.status_code == 404 and "Account not found" in unknown.text
    revoke = d["client"].delete(d["base"] + "/copilot/access/accountant@example.test")
    assert revoke.status_code == 200
    assert d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"},
                            headers={"X-Test-User": "accountant@example.test"}).status_code == 403
    second = d["client"].delete(d["base"] + "/copilot/access/accountant@example.test")
    assert second.status_code == 404 and "Grant not found" in second.text
    events = d["db"].rows(
        "SELECT action,actor FROM audit_events WHERE action LIKE 'copilot.access%' ORDER BY created_at")
    assert [(row["action"], row["actor"]) for row in events] == [
        ("copilot.access_granted", ACTOR), ("copilot.access_revoked", ACTOR)]


def test_access_grant_routes_roles(env, monkeypatch):
    d = env
    enable(d)
    payload = {"email": "viewer@example.test"}
    headers = {"X-Test-User": "accountant@example.test"}
    assert d["client"].get(d["base"] + "/copilot/status", headers=headers).json()["grants"] is None
    assert d["client"].post(d["base"] + "/copilot/access", json=payload, headers=headers).status_code == 403
    assert d["client"].delete(d["base"] + "/copilot/access/viewer@example.test",
                              headers=headers).status_code == 403
    assert d["db"].rows("SELECT id FROM copilot_access_grants") == []
    bad = d["client"].post(d["base"] + "/copilot/access", json={"email": "not-an-email"})
    assert bad.status_code == 422


def test_disabled_org_blocks_even_admins(env, monkeypatch):
    d = env
    provider, call = fake_reply("ok")
    monkeypatch.setattr(copilot, "chat_completion", provider)
    assert d["client"].put(d["base"] + "/copilot/settings", json={"enabled": True}).status_code == 200
    assert d["client"].put(d["base"] + "/copilot/settings", json={"enabled": False}).status_code == 200
    response = d["client"].post(d["base"] + "/copilot/messages", json={"content": "hi"})
    assert response.status_code == 409 and "off for this organisation" in response.text
    assert call["captured"] is None
