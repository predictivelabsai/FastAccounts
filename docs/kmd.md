# KMD coverage and evidence (PR5)

This is an accountant-reviewed workpaper, not a complete filing calculation.
No tax codes, posting workflows, migrations or filing behaviour change in PR5.

## Verified form and vocabulary

Reference: [EMTA KMD form and instructions, valid from 1 July 2025](https://www.emta.ee/sites/default/files/documents/2025-07/vorm_kmd_2025_07_eng.pdf),
pages 1 to 5. The form numbering differs from the proposed PR5 field list:
line 6 is EU acquisitions and qualifying services, line 7 other taxable
acquisitions, line 8 exempt supply, line 9 specified special-arrangement
supplies, and lines 10/11 upward/downward adjustments. These are not generic
reverse-charge VAT boxes. Import VAT belongs to lines 4.1 and 5.1.

`migrations/sqlite/0001_accounting_core.sql` permits `standard`, `reduced`,
`zero`, `exempt`, `out_of_scope`, `reverse_charge` and `intra_eu`.
`organisations.py` seeds EERC as generic reverse charge at 24% and EEICS as
zero-rated intra-Community supply, also used by the VD preparation query.
There are no import, acquisition-specific or non-deductible kinds.
Partial deductibility is a percentage, not evidence of reverse charge.

## Derivation supported today

Qualified case (a) applies: the vocabulary evidences ICS supply, but generic
reverse charge cannot select a detailed KMD field safely.

- `kmd_3_zero_rate_supply`: signed net amounts of posted invoice lines whose
  kind is `zero` or `intra_eu`. This fixes the omission of EEICS from line 3.
- `kmd_3_1_intra_community_supply`: signed net amounts of those invoice lines
  whose kind is `intra_eu`, a subset of line 3. Added only when such rows exist.
  A present set that nets to zero still has a zero value; an absent set has no key.

Both formulas reuse the existing Decimal weighting: credit notes subtract;
cash basis multiplies by the allocated paid/total ratio, capped at one, and
rounds each line to cents. Existing organisation, period and posted-status
filters apply. No amount is inferred from partner country or VAT number.
The source is the existing posted invoice/bill line queries joined to tax codes,
not a new ledger query. They use current tax-code kind, rather than an immutable
posting-time kind snapshot; that pre-existing limitation remains a follow-up.

Warnings accompany ICS supply because goods and services cannot be separated
for 3.1.1. A single warning accompanies reverse-charge sales or purchases:
EERC does not distinguish EU acquisitions, other acquisitions, special domestic
supplies or imports. EEICS on a purchase generates a separate classification
warning because the seeded kind describes supply, not acquisition.
Warnings are returned by `prepare`, using the existing UI translation path;
they are not persisted in the return or included in its CSV.

No new lines 6, 7, 8, 9, 10 or 11, or import subfields, are derived.
In particular, requested reverse-charge lines 7/8/9/11 cannot be populated
under the proposed meanings: these conflict with the verified EMTA form.
Acquisition-side detail and 3.1.1 remain unavailable without more specific
posting evidence. The existing EEEX mapping to 8 is outside this narrow change.

## Existing fields, retained boundaries

| Key | Implemented meaning | Verification and limitation |
| --- | --- | --- |
| `kmd_1_taxable_supply_24` | Signed sales net at 24% | Form line 1; taxable acquisitions are still omitted. |
| `kmd_2_reduced_rate_supply` | Signed sales net at 9% or 13% | Combines form lines 2 and 2.2; not an exact individual form field. Left unchanged. |
| `kmd_3_zero_rate_supply` | Signed zero-rated sales net, now including ICS | Form line 3. |
| `kmd_4_output_vat` | Signed sales tax plus signed EERC purchase tax | Form line 4 VAT concept; does not reconcile all taxable acquisition bases. Left unchanged. |
| `kmd_5_input_vat` | Signed purchase recoverable tax | Form line 5 deductible input VAT concept. |
| `kmd_12_vat_payable` | Output tax minus deductible input tax | Simplified line 12; excludes import VAT and adjustments. Negative results belong to line 13 on the form. Left unchanged. |

All six have identifiable form concepts. The combined line 2 and negative line
12 behaviour cannot be verified as exact form semantics. Their correction,
reverse-charge posting validation and accountant UAT remain follow-up work.
