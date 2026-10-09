# Rebuilding the FastAccounts user guide

The guide follows the sister-repository pattern from **FastShop**
(`docs/USER_GUIDE_BUILD.md`, `scripts/capture_user_guide.py`,
`scripts/build_user_guide.py`, `scripts/build_guide_pptx.py`,
`docs/assets/guide.css`), which in turn follows FastClinic: one Markdown source,
a cover, a contents table with page ranges, section dividers and one slide per
step with the text on the left and the screenshot on the right, rendered to a
landscape PDF and a matching PowerPoint. The English/Estonian pair follows
FastERP's bilingual guides (`_ee` there, `_et` here). The palette is taken from
the workspace design (`static/app.css`); no application styles were changed.

## Sources and outputs

- Editable sources: `docs/USER_GUIDE.md` (English) and `docs/USER_GUIDE_et.md` (Estonian).
- Screenshots: `screenshots/en/` and `screenshots/et/`, 31 each, 1440×1000.
- Dated editions: `docs/fastaccounts_user_guide_<date>.{md,html,pdf,pptx}` and
  `docs/fastaccounts_user_guide_<date>_et.{md,html,pdf,pptx}`; the date and
  version come from `VERSION`.
- Structure: 43 pages/slides, six sections, 32 screenshot slides per language.

## Refresh screenshots

Needs Google Chrome and the Playwright Python package (dev setup). The script
creates a fresh `/tmp/fastaccounts-guide-*` SQLite database per language, seeds
the demo books (including **Demo OÜ (sample payroll)**), serves the app on
`127.0.0.1:5047`, blocks every non-local request and mocks the FastHR API. It
never touches PostgreSQL, production or real credentials; the encryption key is
generated in memory.

```bash
.venv/bin/python -m scripts.capture_user_guide
```

The walk-through also works as a click-through regression of every workspace
area (overview, client switching, invoices, bills, contacts, recurring invoices
and reminders, banking, accounting reports, KMD, payroll employees, part-time
and hourly pay, pay-run wizard, approval, payslip PDF, general ledger,
integrations, the FastHR import review, the employee file import, and email
sign-up and password reset). Reset links stay in memory; no email is sent. It
fails on any browser error or any `/api` response of 400 or above.

## Build both editions

Needs `pandoc` and `pdfinfo` (poppler) from the OS and the Python packages in
`requirements-docs.txt`.

```bash
.venv/bin/pip install -r requirements-docs.txt
.venv/bin/python -m scripts.build_user_guide        # or: ... build_user_guide et
.venv/bin/python -m pytest tests/test_user_guide.py
```

The build checks that every image exists and belongs to the edition's
language, and that the PDF has exactly one page per source slide (no layout
overflow). When adding slides, update the contents ranges and the expected
section positions in `tests/test_user_guide.py`.
