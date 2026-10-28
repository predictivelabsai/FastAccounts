"""Small resident-person extract of EMTA's 18 November 2025 payment matrix."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaymentType:
    code: int
    name: str
    social_tax_rate: Decimal | None
    monthly_minimum_applies: bool
    ui_applies: bool
    ii_pillar_applies: bool
    income_tax_rate: Decimal | None
    tax_free_allowed: bool
    allowed_exemptions: tuple[str, ...]


# Rates and flags are the ordinary resident natural-person rows in the EMTA
# matrix. Duplicated legacy variants that have different rules are kept separate.
PAYMENT_TYPES = {
    10: PaymentType(10, "palgatulu residendile", Decimal("0.33"), True, True, True, Decimal("0.22"), True, ("MVT_610",)),
    11: PaymentType(11, "palgatulu, töö välisriigis, Eesti A1/E101", Decimal("0.33"), True, True, True, None, False, ()),
    12: PaymentType(12, "palgatulu, töö Eestis, välisriigi A1/E101", None, False, False, False, Decimal("0.22"), True, ("MVT_610",)),
    13: PaymentType(13, "kõrgete ametiisikute palgatulu", Decimal("0.33"), True, False, True, Decimal("0.22"), True, ("MVT_610",)),
    14: PaymentType(14, "toetus residendist töötajale lapse sünni puhul", Decimal("0.33"), False, True, True, None, False, ()),
    15: PaymentType(15, "seaduse või õigusakti alusel töö eest makstud tasu", Decimal("0.33"), False, False, False, Decimal("0.22"), True, ("MVT_610",)),
    16: PaymentType(16, "muu töötajale või ametnikule makstud väljamakse", None, False, False, False, Decimal("0.22"), True, ("MVT_610",)),
    17: PaymentType(17, "VÕS lepingu alusel makstud töö- või teenustasu", Decimal("0.33"), False, True, True, Decimal("0.22"), True, ("MVT_610",)),
    21: PaymentType(21, "juriidilise isiku juhtimis- või kontrollorgani liikme tasu", Decimal("0.33"), False, False, True, Decimal("0.22"), True, ("MVT_610",)),
    24: PaymentType(24, "tööandja makstud haigushüvitis", None, False, False, False, Decimal("0.22"), True, ("MVT_610",)),
    32: PaymentType(32, "tööõnnetuse või kutsehaiguse hüvitis", None, False, False, False, Decimal("0.22"), True, ("MVT_610",)),
    33: PaymentType(33, "töölepingu ülesütlemise hüvitis", Decimal("0.33"), True, False, True, Decimal("0.22"), True, ("MVT_610",)),
    120: PaymentType(120, "palgatulu mitteresidendile", Decimal("0.33"), True, True, False, Decimal("0.22"), False, ("MVT_650",)),
}

def payment_type(code: int) -> PaymentType:
    try:
        return PAYMENT_TYPES[int(code)]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"Unsupported TSD payment type: {code}") from exc
