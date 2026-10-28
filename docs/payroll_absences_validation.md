# Payroll absences validation

Date: 2026-10-28. Branch: `feat/payroll-absences`, based on `de88d0f`.

## Unit 1: Payment-type wage and active metadata

Migration 0042 adds organisation payment-type `is_wage` and `active` flags, and
snapshots wage eligibility on saved component rows. Historical wage flags are
backfilled from the migrated preset metadata while temporarily allowing only
that migration backfill through the existing component immutability guard; the
guard is restored immediately. Existing posting data and custom type settings
are retained. New types default to wage and active. Seeded defaults and inactive
history behaviour are documented in `payroll_rules.md`.

Targeted validation command:

```powershell
.tmp\venv312\Scripts\python.exe -m pytest -q -o cache_dir=.tmp\pytest-cache312 --basetemp=.tmp\test-meta-commit tests\test_migrations_and_tenancy.py::test_component_catalogue_upgrade_preserves_defaults_and_posted_payroll tests\test_payroll_demo_fixes.py::test_full_catalogue_defaults_and_descriptions
```

Result: 2 passed. This covers the migration against an approved historical run,
preset metadata and component catalogue defaults. CI migration catalogue and
migration preservation expectations were updated. PostgreSQL SQL substitution
was added but no PostgreSQL server was used.

## Needs accountant confirmation

- Confirm custom payment-type wage eligibility against contracts and source
  documents during bureau setup. The seeded preset mapping is a default only.
- Confirm the statutory average-pay and absence rules against production
  accountant practice before UAT. Items not yet implemented are recorded here
  as the remaining units are developed.
