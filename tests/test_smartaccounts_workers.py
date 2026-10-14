"""Synthetic SmartAccounts payroll snapshots through the reviewed import pipeline."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac

import httpx
import pytest
from cryptography.fernet import Fernet

from connectors.providers import ProviderError, SmartAccountsProvider
from connectors.registry import REGISTRY
from import_service import ImportService
from integration_service import CredentialVault, IntegrationService
from organisations import OrganisationService
from payroll import PayrollService


NO_GROSS = "SmartAccounts worker has no active contract with a gross amount"


def worker(identifier=1, **changes):
    return dict({
        "id": identifier, "forename": "Mari", "surname": "Testmaa",
        "socialSecurityCode": "49003159999", "startDate": "01.01.2025",
        "vendor": {"id": 101, "email": "mari@example.test", "bankAccount": "SYNTHETIC-ACCOUNT"},
        "internalData": "Synthetic private note", "payday": -2,
        "taxSettings": {"incomeTaxFree": True, "sustainSocialTaxMin": True,
                        "noUnempInsurance": False, "disabilityPension": False},
        "fundedPension": {"hasJoined": True, "applicableToday": False},
        "contracts": [{"startDate": "01.02.2025", "endDate": None, "grossSum": "2400.00",
                       "partialWorkload": None, "payoutType": "SALARY"}],
    }, **changes)


def provider_for(payload, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        body = payload(request) if callable(payload) else payload
        return httpx.Response(200, json=body)
    return SmartAccountsProvider(
        "synthetic-public", "synthetic-secret", lang="en",
        clock=lambda: datetime(2026, 10, 14, 12, tzinfo=timezone.utc),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_monthly_worker_mapping_and_signed_request():
    seen = []
    provider = provider_for({"workers": [worker()]}, seen)
    assert "employee" in provider.PULL_OBJECT_TYPES
    result = provider.pull("employee", cursor='{"page":9}')
    record = result.records[0]
    request = seen[0]
    assert request.url.path == "/en/api/payroll/workers:get"
    assert request.url.params["fetchContracts"] == "true"
    assert request.url.params["pageNumber"] == "1"
    query, signature = request.url.query.decode().rsplit("&signature=", 1)
    assert signature == hmac.new(b"synthetic-secret", query.encode(), hashlib.sha256).hexdigest()
    assert record == {
        "external_id": "1", "name": "Mari Testmaa", "personal_id": "49003159999",
        "email": "mari@example.test", "pay_basis": "monthly", "gross_salary": Decimal("2400.00"),
        "fte": Decimal("1.0000"), "apply_tax_free_minimum": True,
        "funded_pension_percent": Decimal("0"), "active": True,
        "employment_start_date": "2025-02-01", "smartaccounts_sustain_social_tax_min": True,
        "smartaccounts_no_unemployment_insurance": False, "smartaccounts_disability_pension": False,
        "smartaccounts_payday": -2, "smartaccounts_payout_types": ["SALARY"],
        "smartaccounts_vendor_id": 101,
    }
    assert isinstance(record["gross_salary"], Decimal)
    assert isinstance(record["fte"], Decimal)
    assert result.cursor is None


def test_part_time_ended_and_future_workers():
    rows = [
        worker(2, contracts=[{"startDate": "2025-01-01", "grossSum": "1500", "partialWorkload": "0.5"}]),
        worker(3, endDate="13.10.2026"),
        worker(4, contracts=[{"startDate": "01.11.2026", "grossSum": "2700"}]),
    ]
    part, ended, future = provider_for({"workers": rows}).pull("employee").records
    assert part["gross_salary"] == Decimal("1500.00")
    assert part["fte"] == Decimal("0.5000")
    assert ended["active"] is False
    assert ended["employment_end_date"] == "2026-10-13"
    assert future["gross_salary"] == Decimal("2700.00")
    assert future["employment_start_date"] == "2026-11-01"


@pytest.mark.parametrize("field", ["type", "grossType", "salaryType", "payType"])
@pytest.mark.parametrize("value", ["HOUR", "Hourly", "tund", "TUNNIS"])
def test_hourly_contract_aliases(field, value):
    row = worker(contracts=[{"startDate": "2025-01-01", "grossSum": "12.3456", field: value}])
    record = provider_for({"workers": [row]}).pull("employee").records[0]
    assert record["pay_basis"] == "hourly"
    assert record["hourly_rate"] == Decimal("12.3456")
    assert "gross_salary" not in record


def test_contract_selection_sums_and_pension_assumptions():
    contracts = [
        {"startDate": "2024-01-01", "endDate": "2024-12-31", "grossSum": "9999"},
        {"startDate": "2025-01-01", "grossSum": "1000.005", "partialWorkload": "0.3"},
        {"startDate": "14.10.2026", "endDate": "14.10.2026", "grossSum": "500.005", "partialWorkload": "0.5"},
        {"startDate": "2027-01-01", "grossSum": "9999"},
    ]
    record = provider_for({"workers": [worker(contracts=contracts, fundedPension={"hasJoined": True})]}).pull("employee").records[0]
    assert record["gross_salary"] == Decimal("1500.01")
    assert record["fte"] == Decimal("0.5000")
    assert record["employment_start_date"] == "2024-01-01"
    assert record["funded_pension_percent"] == Decimal("2")
    assert record["smartaccounts_funded_pension_rate_assumed"] is True
    contracts[1]["type"] = "hourly"
    contracts[2]["payType"] = "hourly"
    record = provider_for({"workers": [worker(contracts=contracts)]}).pull("employee").records[0]
    assert record["hourly_rate"] == Decimal("1500.0100")


def test_latest_start_fallback_keeps_all_matching_contracts():
    contracts = [{"startDate": "2024-01-01", "endDate": "2024-02-01", "grossSum": "9000"},
                 {"startDate": "2027-01-01", "grossSum": "1000", "partialWorkload": "0.3"},
                 {"startDate": "2027-01-01", "grossSum": "500", "partialWorkload": "0.5"}]
    record = provider_for({"workers": [worker(contracts=contracts)]}).pull("employee").records[0]
    assert record["gross_salary"] == Decimal("1500.00")
    assert record["fte"] == Decimal("0.5000")


@pytest.mark.parametrize("workload", ["0", "-0.5", "1.1"])
def test_invalid_workload_is_flagged(workload):
    row = worker(contracts=[{"startDate": "2025-01-01", "grossSum": "1500", "partialWorkload": workload}])
    assert provider_for({"workers": [row]}).pull("employee").records[0]["import_warning"] == "SmartAccounts worker has an invalid workload"


def test_missing_name_and_contracts_are_flagged():
    records = provider_for({"workers": [worker(contracts=[]), worker(2, forename=" ", surname="")]}).pull("employee").records
    assert records[0]["import_warning"] == NO_GROSS
    assert records[0]["employment_start_date"] == "2025-01-01"
    assert records[1]["import_warning"] == "SmartAccounts worker has no name"


def test_all_worker_pages_are_read_without_a_cursor():
    seen = []
    def payload(request):
        page = int(request.url.params["pageNumber"])
        return {"workers": [worker(page)], "hasMoreEntries": page < 3}
    result = provider_for(payload, seen).pull("employee", cursor="old page cursor")
    assert [record["external_id"] for record in result.records] == ["1", "2", "3"]
    assert result.cursor is None
    assert len(seen) == 3
    assert all(request.url.params["fetchContracts"] == "true" for request in seen)


def test_worker_page_limit():
    seen = []
    with pytest.raises(ProviderError, match="50-page"):
        provider_for({"workers": [], "hasMoreEntries": True}, seen).pull("employee")
    assert len(seen) == 50


@pytest.mark.parametrize("payload", [{"error": "synthetic error", "workers": []},
                                         {"errors": ["synthetic error"]}, {"workers": [{}]}])
def test_error_envelope_and_missing_identifier(payload):
    with pytest.raises(ProviderError):
        provider_for(payload).pull("employee")


def import_service(db, ee_org, monkeypatch, workers):
    integration = IntegrationService(db, CredentialVault(Fernet.generate_key().decode()))
    integration.configure(ee_org["id"], "smartaccounts",
                          credentials={"api_key": "synthetic-public", "secret_key": "synthetic-secret"},
                          config={}, actor="owner@example.test")
    provider = provider_for({"workers": workers})
    monkeypatch.setitem(REGISTRY, "smartaccounts", replace(REGISTRY["smartaccounts"],
                        factory=lambda credentials, config: provider))
    return ImportService(db, integration=integration)


def sync_and_apply(service, organisation_id):
    sync = service.run_sync(organisation_id, "smartaccounts", "employee", actor="owner@example.test")
    staged = service.get_staged(organisation_id, sync_run_id=sync["id"])["records"]
    result = service.apply_staged(organisation_id, "smartaccounts", sync["id"],
                                 {record["id"]: "apply" for record in staged}, actor="owner@example.test")
    return staged, result


def test_workers_import_and_repeat_are_idempotent(db, ee_org, monkeypatch):
    workers = [worker(), worker(2, forename="Jaan", surname="Proovikask", socialSecurityCode="38511209998",
                               vendor={"email": "jaan@example.test"},
                               contracts=[{"startDate": "2025-01-01", "grossSum": "1500", "partialWorkload": "0.5"}]),
               worker(3, forename="Liis", surname="Naidisvoru", socialSecurityCode="49507079998",
                      vendor={"email": "liis@example.test"})]
    service = import_service(db, ee_org, monkeypatch, workers)
    staged, applied = sync_and_apply(service, ee_org["id"])
    assert len(staged) == 3
    assert applied["applied"] == 3 and applied["failed"] == 0
    employees = PayrollService(db).employees(ee_org["id"])
    assert {employee["name"]: Decimal(employee["gross_salary"]) for employee in employees} == {
        "Mari Testmaa": Decimal("2400.00"), "Jaan Proovikask": Decimal("1500.00"),
        "Liis Naidisvoru": Decimal("2400.00")}
    repeated, result = sync_and_apply(service, ee_org["id"])
    assert all(record["matched_local_employee_id"] for record in repeated)
    assert result["unchanged"] == 3 and result["failed"] == 0
    assert len(PayrollService(db).employees(ee_org["id"])) == 3


def test_worker_without_contracts_fails_apply_with_warning(db, ee_org, monkeypatch):
    service = import_service(db, ee_org, monkeypatch, [worker(contracts=[])])
    staged, result = sync_and_apply(service, ee_org["id"])
    assert staged[0]["review_note"] == NO_GROSS
    assert result["failed"] == 1
    assert result["outcomes"][0]["reason"] == NO_GROSS
    assert PayrollService(db).employees(ee_org["id"]) == []


@pytest.mark.parametrize("match_field", ["personal_id", "email", "name"])
def test_existing_employee_matching_is_tenant_scoped(db, ee_org, monkeypatch, match_field):
    other_org = OrganisationService(db).create(
        name="Other Synthetic Eesti OU", country_code="EE", entity_type="EE_OU",
        owner_email="other@example.test", registration_no="87654321",
    )
    row = worker()
    if match_field == "name":
        row.pop("socialSecurityCode")
        row["vendor"] = {}
    payroll = PayrollService(db)
    values = {"name": "Mari Testmaa" if match_field == "name" else "Original synthetic name",
              "gross_salary": Decimal("1000"), match_field: {
                  "personal_id": "49003159999", "email": "mari@example.test", "name": "Mari Testmaa"}[match_field]}
    payroll.save_employee(other_org["id"], actor="owner@example.test", **values)
    local = payroll.save_employee(ee_org["id"], actor="owner@example.test", **values)
    service = import_service(db, ee_org, monkeypatch, [row])
    staged, result = sync_and_apply(service, ee_org["id"])
    assert staged[0]["matched_local_employee_id"] == local["id"]
    assert result["updated"] == 1 and result["failed"] == 0
    assert Decimal(payroll.employees(other_org["id"])[0]["gross_salary"]) == Decimal("1000")
