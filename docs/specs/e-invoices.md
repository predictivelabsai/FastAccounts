# PR3: Estonian e-invoice export and purchase intake

Create a review-gated, isolated e-arve 1.2 writer and validating parser. Export
only issued sales invoices. Import one XML invoice into a draft purchase bill
with an organisation-scoped supplier, numeric VAT mapping and source evidence.
Keep supplier, bill and evidence changes atomic. No migration or CI change.

Independent work packages:

1. `einvoice.py`, synthetic fixtures and module tests: Decimal arithmetic,
   namespace independence, declaration checks and round-trip validation.
2. `documents.py`, `api_app.py` and integration tests: export gate, supplier
   resolution, duplicate handling, draft creation and evidence preservation.
3. `static/app.js`, four locale catalogues and optional Playwright test:
   accessible file picker and navigation to the imported draft bill.
4. Provider scaffold, registry/catalogue and synchronised roadmap/change log:
   blocked operator submission pending Finbite/Omniva contracts.

Acceptance: focused tests, `python -m pytest tests/ -q` and
`python -m compileall -q .` pass. Preserve UK XML behaviour and tenant scoping.
Fixtures are synthetic. Schema/XSD and operator live verification are outside
scope and require accountant review and operator contracts respectively.
