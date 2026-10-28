"""Pure allocation of frozen aggregate payroll taxes to TSD payment types."""
from decimal import Decimal

from core_utils import decimal, money
from payroll_tsd_types import payment_type

LINE_FIELDS = ("payment_type", "amount", "social_tax_base", "social_tax",
               "social_tax_minimum_topup", "ui_employee_base", "ui_employee",
               "ui_employer_base", "ui_employer", "ii_pillar_base", "ii_pillar",
               "exemption_610", "taxable_amount", "income_tax")


def tsd_lines_table_ready(tx):
    if tx.dialect == "postgres":
        return bool(tx.one("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='pay_item_tsd_lines'"))
    return bool(tx.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pay_item_tsd_lines'"))


def _allocate(total, weights):
    """Allocate cents by weight; rounding residual goes to the largest record."""
    total = money(total)
    positive = {key: max(Decimal(0), decimal(value)) for key, value in weights.items()}
    denominator = sum(positive.values(), Decimal(0))
    if not positive:
        return {}
    if denominator == 0:
        if total:
            raise ValueError("Frozen levy total has no eligible payment-type base")
        return {key: money(0) for key in positive}
    result = {key: money(total * value / denominator) for key, value in positive.items()}
    residual = total - sum(result.values(), Decimal(0))
    largest = max(positive, key=lambda key: (positive[key], -key))
    result[largest] += residual
    return result


def calculate_tsd_breakdown(*, item, components, context):
    """Return frozen per-type lines that reconcile to ``item`` aggregate values.

    Component levy flags and payment codes are read only from the supplied frozen
    component rows. The base salary is represented by the pay item's own frozen
    payment code. Aggregate levy rounding differences are assigned to the largest
    eligible record for that levy.
    """
    grouped = {}

    def add(code, amount, flags):
        code = int(code)
        payment_type(code)
        record = grouped.setdefault(code, {
            "payment_type": code, "amount": Decimal(0),
            "income_tax_base": Decimal(0), "social_tax_base": Decimal(0),
            "ui_employee_base": Decimal(0), "ui_employer_base": Decimal(0),
            "ii_pillar_base": Decimal(0),
        })
        amount = money(amount)
        record["amount"] += amount
        for flag, field in (("income_tax", "income_tax_base"),
                            ("social_tax", "social_tax_base"),
                            ("ui_employee", "ui_employee_base"),
                            ("ui_employer", "ui_employer_base"),
                            ("funded_pension", "ii_pillar_base")):
            if flags.get(flag):
                record[field] += amount

    salary_amount = money(decimal(item["gross"]) - sum((money(c["amount"]) for c in components
                                                          if c["direction"] == "income"), Decimal(0)))
    if salary_amount < 0:
        salary_amount = Decimal(0)
    add(item.get("tsd_payment_type") or {"monthly": 10, "hourly": 10,
        "board_fee": 21, "income_line": 17}[item["pay_basis"]], salary_amount,
        {"income_tax": True, "social_tax": True, "ui_employee": item["pay_basis"] != "board_fee",
         "ui_employer": item["pay_basis"] != "board_fee", "funded_pension": True})
    for component in components:
        if component["direction"] != "income":
            continue
        add(component.get("tsd_payment_type", 10), component["amount"], component)

    # A type can have a zero amount only when the item itself is zero-gross.
    records = [grouped[key] for key in sorted(grouped)]
    if not records:
        return []
    by_code = {row["payment_type"]: row for row in records}
    aggregate = lambda key: money(item.get(key, 0))

    for levy, base_field, amount_field in (
        ("social_tax", "social_tax_base", "social_tax"),
        ("ui_employee", "ui_employee_base", "ui_employee"),
        ("ui_employer", "ui_employer_base", "ui_employer"),
        ("funded_pension", "ii_pillar_base", "ii_pillar"),
    ):
        if levy == "social_tax":
            raw = sum((r[base_field] for r in records), Decimal(0))
            topup = money(max(Decimal(0), aggregate("social_tax_base") - raw))
            if topup:
                eligible = [r for r in records if payment_type(r["payment_type"]).monthly_minimum_applies]
                if not eligible:
                    raise ValueError("Frozen social-tax top-up has no eligible payment type")
                salary_record = by_code.get(10) if by_code.get(10) in eligible else min(eligible, key=lambda r: r["payment_type"])
                salary_record[base_field] += topup
                salary_record["social_tax_minimum_topup"] = topup
        levy_total = aggregate({"social_tax": "social_tax", "ui_employee": "ui_employee",
                                "ui_employer": "ui_employer", "funded_pension": "funded_pension"}[levy])
        shares = _allocate(levy_total, {r["payment_type"]: r[base_field] for r in records})
        for row in records:
            row[amount_field] = shares[row["payment_type"]]

    taxable_weights = {r["payment_type"]: max(Decimal(0), r["income_tax_base"] - r["ii_pillar"] - r["ui_employee"])
                       for r in records}
    exemption_total = aggregate("tax_free_minimum")
    exemptions = {}
    left = exemption_total
    eligible_records = [row for row in records if "MVT_610" in payment_type(row["payment_type"]).allowed_exemptions]
    ordered = sorted(eligible_records, key=lambda r: (r["payment_type"] != 10, r["payment_type"]))
    for row in ordered:
        code = row["payment_type"]
        applied = min(left, taxable_weights[code])
        exemptions[code] = money(applied)
        left -= applied
    if left > 0:
        raise ValueError("Frozen tax-free amount exceeds eligible payment-type taxable amounts")

    for row in records:
        code = row["payment_type"]
        row["exemption_610"] = exemptions.get(code, Decimal(0)) if "MVT_610" in payment_type(code).allowed_exemptions else Decimal(0)
        row["taxable_amount"] = money(max(Decimal(0), taxable_weights[code] - row["exemption_610"]))
    income_tax = _allocate(aggregate("income_tax"), {r["payment_type"]: r["taxable_amount"] for r in records})
    for row in records:
        row["income_tax"] = income_tax[row["payment_type"]]
        row.setdefault("social_tax_minimum_topup", Decimal(0))
        for field in ("amount", "social_tax_base", "social_tax", "social_tax_minimum_topup",
                      "ui_employee_base", "ui_employee", "ui_employer_base", "ui_employer",
                      "ii_pillar_base", "ii_pillar", "exemption_610", "taxable_amount", "income_tax"):
            row[field] = money(row[field])
    return records


def freeze_tsd_breakdown(tx, organisation_id, source_kind, source_id, *, item, components, context,
                         payout_batch_id=None):
    """Persist a breakdown inside the caller's approval transaction."""
    if not tsd_lines_table_ready(tx):
        return []
    records = calculate_tsd_breakdown(item=item, components=components, context=context)
    for record in records:
        payment = payment_type(record["payment_type"])
        tx.execute(
            "INSERT INTO pay_item_tsd_lines(id,organisation_id,source_kind,source_id,payout_batch_id,payment_type,payment_type_name,amount,"
            "social_tax_base,social_tax,social_tax_minimum_topup,ui_employee_base,ui_employee,ui_employer_base,ui_employer,"
            "ii_pillar_base,ii_pillar,exemption_610,taxable_amount,income_tax) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"{source_id}:{payout_batch_id or 'run'}:{record['payment_type']}", organisation_id, source_kind, source_id, payout_batch_id,
             record["payment_type"], payment.name, *(str(record[field]) for field in LINE_FIELDS[1:])),
        )
    return records
