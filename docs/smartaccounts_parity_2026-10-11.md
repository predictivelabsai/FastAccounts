# SmartAccounts feature parity, 11 October 2026

## 1. Purpose and sourcing

Assess FastAccounts against SmartAccounts for UK and Estonian small-business bookkeeping, identifying switching barriers, product-boundary differences and practical priorities. This compares recorded capabilities, rather than certifying deployed behaviour, legal compliance or reliability.

Sources: SmartAccounts UI capture dated **2026-10-11**, from the operator's own company account at smartaccounts.eu, and FastAccounts code audit dated **2026-10-11**, both by automated read-only inventory. Read in full: [smartaccounts_features.md](../../smartaccounts-audit/smartaccounts_features.md) (SA) and [fastaccounts_features.md](../../smartaccounts-audit/fastaccounts_features.md) (FA). SA derives from 79 text captures, with capture filenames and evidence notes; FA audits committed HEAD (version 0.4.0) and separately labels working-tree work. References below use the source inventories' section numbers. No additional browsing or live operations were used.

## 2. Executive summary

SmartAccounts has **474 feature bullets** across sections 1-12, represented by **474 matrix rows**. FastAccounts fully covers **22 rows as Have (4.6% of all bullets)**, with **124 Partial**, **281 Missing** and **47 n/a**. Excluding n/a gives **427 applicable rows**, with **5.2% Have**. Partial includes shipped subsets, service-only functionality and explicitly uncommitted work, contributing zero to fully covered counts. This is conservative inventory-bullet coverage, not a unique-feature total or weighted commercial score: exports, reports, settings and integrations overlap, and some bullets bundle controls. Shipped API coverage can qualify as Have where it meets the stated need, with missing workspace forms disclosed.

FastAccounts has a shipped foundation in invoices, bill review/approval, reviewed bank reconciliation, immutable ledger batches, core reports and 2026 Estonian demo payroll. Switching barriers centre on the connected operational and statutory workflows around it. Inventory/order management remain outside this repository's product boundary; their commercial absence limits customer segments and calls for sister-product integrations.

The ten highest-impact gaps, ranked by likely switching friction (analytical judgement, not customer research):

1. **Live Estonian bank feeds (Pangamaksete import), Partial.** Removing repeated statement uploads is central to accountants managing many client books. (SA §§3,11; FA §§7,16.)
2. **Verified e-invoice sending/receiving (e-arved), Partial.** Operator delivery and a reviewed purchase inbox remove manual handling for businesses already using e-invoices. (SA §§1,2,11; FA §§4,6,17.)
3. **Complete declarations (KMDd / TSDd) and Estonian Tax and Customs Board filing (Maksu- ja Tolliamet / EMTA), Partial.** Accountants need dependable statutory coverage and filing receipts before replacing their primary accounting system. (SA §§6,9,11; FA §§9,16,17.)
4. **Payment-order export (Maksekorralduste eksport), Missing.** Supplier payment batches avoid re-keying bank details and make payables viable at volume. (SA §3; FA §§7,17.)
5. **Migration and opening balances (Kliendid / Hankijad, opening invoices), Missing.** Switching is costly when counterparties, outstanding invoices and balances must be entered manually. (SA §§1,2,4; FA §§3,8,11,17.)
6. **Payroll leave/sickness/payout depth (Puhkused/puudumised / Töötasud), Partial.** Salary and board-fee demos alone cannot retain bureaus serving routine leave and sickness cases. (SA §9; FA §§10,16,17.)
7. **Fixed assets/depreciation (Põhivarad / Amortiseerimised), Missing.** Asset-owning companies otherwise need a parallel register and recurring manual journals. (SA §8; FA §17.)
8. **Statement-of-account PDFs (Saldoteatis), Missing.** Accountants need distributable balance confirmations for collections and year-end checks. (SA §§5,12; FA §8.)
9. **Customer/vendor prepayments (Klientide ettemaksed / Hankijate ettemaksed), Missing.** Businesses taking deposits need explicit advances and later allocations without spreadsheets. (SA §§3,5; FA §§7,17.)
10. **Cash-flow/comparative reports (Rahavoogude aruanne), Missing.** Founders need cash movement and period comparisons beyond profit figures and bank-movement charts. (SA §5; FA §§8,12,17.)

## 3. Priority gap list

P0 marks potential Estonian accountant/founder switching blockers; P1 substantial module/workflow absences; P2 operational depth or polish. Priorities do not authorise widening scope. Priority statuses use Have/Partial/Missing; deliberate out-of-boundary absences are commercially Missing here and n/a in the matrix.

### P0, switching barriers

- **Live Estonian bank feeds (Pangamaksete import): Partial.** SA §§3,11; FA §§7,16. CSV/CAMT upload is shipped; GoCardless primitives are partial and no live consent/feed/reconnect journey is routed.
- **Verified e-invoice sending/receiving (e-arved): Partial.** SA §§1,2,11; FA §§4,6,17. Review XML export is shipped; operator delivery and inbound processing are Missing.
- **Complete declarations and EMTA filing (KMDd / TSDd): Partial.** SA §§6,9,11; FA §§9,16,17. KMD workpapers are a shipped subset, TSD is uncommitted and unverified, and direct EMTA filing is Missing.
- **Payment-order export (Maksekorralduste eksport): Missing.** SA §3; FA §§7,17. No routed equivalent established.
- **Migration and opening balances (Kliendid / Hankijad, opening invoices): Missing.** SA §§1,2,4; FA §§3,8,11,17. No routed equivalent established.
- **Payroll leave/sickness/payout depth (Puhkused/puudumised / Töötasud): Partial.** SA §9; FA §§10,16,17. Monthly/hourly salary and board fees are shipped demo capabilities; leave/sickness pay and the broad payout catalogue are Missing.
- **Annual-report export (Majandusaasta aruanne): Missing.** No annual XBRL/note workflow; ordinary balance sheet/P&L shipped. SA §5; FA §§8,17.
- **Invoice/receipt intake (Ootel ostuarved): Partial.** Bill review exists, provider inbox/digitised intake and attachment UI absent. SA §§2,11; FA §§6,13,17.

### P1, module and workflow absences

- **Quotes (Pakkumised): Missing.** No quotation/conversion surface. SA §1; FA §§4,17.
- **Client/purchase orders (Tellimused / Ostutellimused): Missing, outside scope.** Integrate sister products. SA §§1,2; FA §17.
- **Inventory/FIFO costing (Laod / Laoliikumised): Missing, outside scope.** Stock businesses need external integration. SA §§5,7; FA §§13,17.
- **Fixed assets/depreciation (Põhivarad / Amortiseerimised): Missing.** No register, worker or carrying-value report. SA §8; FA §17.
- **Cash flow/comparisons (Rahavoogude aruanne): Missing.** Cash summary/chart cover a different need. SA §5; FA §§8,12,17.
- **Balance-confirmation PDFs (Saldoteatis): Missing.** Ageing/browser print do not provide these statements. SA §§5,12; FA §8.
- **Prepayments (Klientide ettemaksed / Hankijate ettemaksed): Missing.** Invoice allocations exist, explicit advance subledger absent. SA §§3,5; FA §§7,17.
- **Purchase periodisation (Periodiseeritud / Periodiseerimata): Missing.** SA filter visible, setup unconfirmed; no FA workflow. SA §2; FA §6.
- **Payment links (EveryPay / LinkPay): Missing.** PDF/email delivery does not collect payment. SA §§1,11; FA §§5,17.
- **Analytical objects (Objektid): Missing.** No document/line dimensions or object reports. SA §§1,2,4,5,10; FA §§4,6,8,17.

### P2, operational depth and polish

- **Exports/configurable fields (displayed fields): Partial.** Individual PDFs, tax CSV/browser printing shipped; GL CSV service only; list XLS/CSV/bulk downloads missing. SA §§1-10,12; FA §§4,8,9,10,13.
- **Templates/colours (Dokumendimallid / E-kirjad): Partial.** Fixed output and recurring/reminder delivery shipped, no customer editor/SMTP choice. SA §10; FA §§4,5,17.
- **Contact/user groups (Kliendid / Hankijad / Kasutajagrupid): Partial.** Contact roles/fixed permissions shipped, editable groups absent. SA §§1,2,10; FA §§1,3.
- **Multi-factor authentication (MFA): Missing.** Google/local login exists, explicit MFA workflow unestablished. SA §10; FA §1.
- **Bulk VAT replacement (VAT-rate replacement): Missing.** Read-only seeded codes, no preview/confirmation/scheduling tool. SA §6; FA §§2,9,17.
- **Maintenance/reference numbers (Parameetrid): Missing.** No orphan-counterparty cleanup/reference-generation/counting controls. SA §10; FA §§3,17.
- **Company/account/tax/series settings (Kontoplaan / Parameetrid): Partial.** Initial defaults shipped, maintenance surface absent. SA §10; FA §§2,17.
- **Period locks/close controls (transaction locking date): Partial.** Enforcement shipped, lock/reversal/checklist service only, no close/reopen UI. SA §10; FA §§8,13,17.
- **Exchange rates (EKP kurss): Missing.** Currency fields do not establish rates/conversion/revaluation. SA §§10,12; FA §§2,17.

## 4. Area-by-area parity matrix

**Have** means committed Shipped coverage for the stated need. **Partial** means a shipped subset, service-only implementation or uncommitted work, identified in Notes. **Missing** means no equivalent established by FA. **n/a** means scope exclusion or vendor-specific feature, with reason. Estonian regulatory features apply to Estonian books and are not excluded simply because UK rules differ. Each row corresponds to one SA bullet, in source order, without deduplication; bundled bullets remain bundled. Group labels preserve repeated export/filter context.

### 1. Sales

Source: SA §1, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Client offers / quotes (Pakkumised)**: Create quotes and expose an edit action. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Filter quotes by date range and status. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Track draft, sent/pending, confirmed, rejected, other, lead, awaiting dispatch and fulfilled statuses. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Represent order, advance invoice, invoice and sales invoice creation through quote statuses; conversion controls were not captured. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Configure quote numbering and default validity in calendar days. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Use quote document and email templates. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Export lists as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client offers / quotes (Pakkumised)**: Configure displayed fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Client orders (Tellimused)**: Create orders and expose an edit action. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Filter orders by date range and status. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Track draft, sent/pending, confirmed, rejected, other, ordered, fulfilled and in-stock statuses. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Represent advance invoice, sales invoice, purchase invoice, purchase order and invoice creation through order statuses. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Configure numbering and default payment terms. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Use order document and email templates. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Export lists as PDF, XLS or CSV. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Client orders (Tellimused)**: Configure displayed fields and download attachments in bulk. | n/a | Order management is outside the product boundary; a sister-product integration is needed (FA §17). |
| **Sales invoices (Müügiarved)**: Maintain client, invoice number/date, posting date, due date, daily late-interest percentage, warehouse, reference number, currency and invoice-level object. | Partial | Customer, issue/due dates and numbering shipped; API reference/currency. No late-interest, warehouse or object controls (FA §4). |
| **Sales invoices (Müügiarved)**: Add/delete invoice lines with item, description, quantity, price, discount percentage (AH %), amount, VAT, account and line-level object; a column labelled M± is present but its meaning is not explained. | Partial | New-document lines support description, quantity, price, tax/accounts; API multiline, UI one line. No draft editing, item picker, discounts or objects (FA §§4,13). |
| **Sales invoices (Müügiarved)**: Show net amount, VAT, rounding, total and unpaid amount. | Partial | Net/tax/gross and payment progress shipped; separate rounding display unconfirmed (FA §4). |
| **Sales invoices (Müügiarved)**: Record a payment alongside the invoice using a selected payment method and amount. | Partial | Reviewed bank reconciliation allocates receipts; direct record_payment is service only, no invoice-form payment action (FA §§7,13). |
| **Sales invoices (Müügiarved)**: Add a cash/bank payment from the invoice form. | Partial | Reviewed bank reconciliation allocates receipts; direct record_payment is service only, no invoice-form payment action (FA §§7,13). |
| **Sales invoices (Müügiarved)**: Select an Estonian, English or Russian PDF template for an invoice. | Partial | PDF download shipped; selectable EE/EN/RU template catalogue absent (FA §4). |
| **Sales invoices (Müügiarved)**: Maintain invoice additional information, internal information and uploaded files using drag-and-drop/file selection. | Partial | API notes shipped; attachment storage service only, no upload/library (FA §§4,13). |
| **Sales invoices (Müügiarved)**: Filter invoice types as sales invoices, credit notes or recurring invoices, and select a recurring-invoice type. | Partial | Invoices/API credits shipped, schedules separate; these type filters absent (FA §§4,5). |
| **Sales invoices (Müügiarved)**: Filter sending status as unsent, sent by email or sent through the invoice centre. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Create sales invoices. | Have | Draft creation and issue through UI/API (FA §4). |
| **Sales invoices (Müügiarved)**: Filter by unpaid or overdue payment status. | Partial | Overdue filter shipped; separate unpaid filter unconfirmed (FA §4). |
| **Sales invoices (Müügiarved)**: Filter date ranges using invoice date, posting date, due date or creation date. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Export the list as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Export invoice PDFs in bulk. | Partial | Single invoice PDF shipped; no bulk PDF export (FA §4). |
| **Sales invoices (Müügiarved)**: Export e-invoices. | Partial | Review XML shipped; Estonian schema/operator acceptance unverified (FA §§4,17). |
| **Sales invoices (Müügiarved)**: Send e-invoices through an exposed action. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Send invoices from the list, including bulk sending described by recurring-invoice guidance. | Partial | Manual email service only; recurring auto-email shipped, no general list/bulk sending (FA §§5,13). |
| **Sales invoices (Müügiarved)**: Convert existing invoices into recurring arrangements individually or in bulk. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Configure displayed fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Configure sales invoice and credit note numbering separately; a complete credit note workflow was not captured. | Partial | Default separate INV-/CRN- sequences/API credits shipped; no pattern editor (FA §§2,4). |
| **Sales invoices (Müügiarved)**: Configure default late-payment interest and payment terms. | Partial | Contact terms/API due-date defaults shipped; no late-interest setting (FA §§3,4). |
| **Sales invoices (Müügiarved)**: Configure payment reference number type and length. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Sales invoices (Müügiarved)**: Use invoice document/email templates and EveryPay payment links. | Partial | PDF and recurring/reminder delivery shipped, no template editor or EveryPay (FA §§4,5,17). |
| **Recurring invoices (Perioodilised arved)**: Create recurring invoice contracts directly. | Have | Named template-based schedules through UI/API cover direct creation (FA §5). |
| **Recurring invoices (Perioodilised arved)**: Create contracts from one existing invoice or several selected invoices. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Recurring invoices (Perioodilised arved)**: Generate invoices in batches with **Compose invoices** (Koosta arved), described as a periodic user action, for example monthly. | Partial | Due worker with bounded catch-up and run-now shipped; no selected-contract batch screen (FA §5). |
| **Recurring invoices (Perioodilised arved)**: Review or amend generated invoices in the sales invoice list before sending. | Partial | Inspect generated invoices, but cannot amend them; run-now issues invoices (FA §§4,5). |
| **Recurring invoices (Perioodilised arved)**: Send generated invoices in bulk from that list. | Partial | Manual email service only; recurring auto-email shipped, no general list/bulk sending (FA §§5,13). |
| **Recurring invoices (Perioodilised arved)**: Manage recurring invoice types through a linked action. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Recurring invoices (Perioodilised arved)**: Export contracts as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Recurring invoices (Perioodilised arved)**: Configure displayed fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Recurring invoices (Perioodilised arved)**: **Automation hint:** profile preferences offer notifications of automatic recurring invoice creation. This suggests an automatic mode, but its activation and scheduling controls are absent; the recurring page explains manual batch creation. | Have | Configured worker provides automatic creation; SmartAccounts scheduling evidence is only a hint (FA §5). |
| **Reminders (Meeldetuletused)**: Define unpaid-invoice reminder rules on, before or after the due date. | Partial | Fixed -3/+7/+14-day stages shipped; rules/timing not user-configurable (FA §5). |
| **Reminders (Meeldetuletused)**: Set the number of days before or after the due date. | Partial | Fixed -3/+7/+14-day stages shipped; rules/timing not user-configurable (FA §5). |
| **Reminders (Meeldetuletused)**: **Automation:** enable automatic reminder creation independently of sending. | Partial | Due-reminder listing/manual send/opt-out shipped, no independent automatic-create switch (FA §5). |
| **Reminders (Meeldetuletused)**: **Automation:** enable automatic sending of created reminders. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Reminders (Meeldetuletused)**: Add or delete multiple reminder rules. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Reminders (Meeldetuletused)**: Assign a different email template to each rule. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Reminders (Meeldetuletused)**: Open email-template settings from reminder configuration. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Reminders (Meeldetuletused)**: Link to bank integrations to keep receipt information current. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Create and open client records. | Have | Customer contacts created/listed/selected through UI/API; no edit route (FA §3). |
| **Clients (Kliendid)**: Maintain name, registration number, VAT registration number, group, address and contacts. | Partial | Name/registration/VAT/address/email shipped; groups and broader editing absent (FA §3). |
| **Clients (Kliendid)**: Manage client groups through a linked page. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Import and export client master data. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Import opening balances through an opening-invoices action. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Export the list as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Sort identifying columns and configure displayed fields. | Missing | No equivalent routed capability established (FA §§4,5,17). |
| **Clients (Kliendid)**: Download attachments in bulk. | Missing | No equivalent routed capability established (FA §§4,5,17). |

### 2. Purchases

Source: SA §2, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Vendor invoices (Ostuarved)**: Maintain vendor, invoice number/date, posting date, due date, daily late-interest percentage, warehouse, reference number, currency and invoice-level object. | Partial | Supplier/document/due dates and API currency/reference shipped; posting-date, late-interest, warehouse/objects absent (FA §6). |
| **Vendor invoices (Ostuarved)**: Add/delete invoice lines with item, description, quantity, price, amount, VAT, account and line-level object. | Partial | New bill lines with price/tax/accounts; API multiline/UI one line, no editor/item picker/objects (FA §§6,13). |
| **Vendor invoices (Ostuarved)**: Show net amount, VAT, rounding, total and unpaid amount. | Partial | Calculated totals/paid progress shipped; separate rounding display unconfirmed (FA §6). |
| **Vendor invoices (Ostuarved)**: **Automation:** expose an automatic-calculation option beside purchase invoice totals; its exact calculation scope is not explained. | Partial | Automatic bill/tax calculation shipped; equivalence to unexplained toggle unverified (FA §§6,9). |
| **Vendor invoices (Ostuarved)**: Record a payment alongside a purchase invoice with payment method and amount. | Partial | Reconciliation allocates payments; direct payment service only, no bill-form cash/bank action (FA §§7,13). |
| **Vendor invoices (Ostuarved)**: Add a cash/bank payment from the purchase invoice form. | Partial | Reconciliation allocates payments; direct payment service only, no bill-form cash/bank action (FA §§7,13). |
| **Vendor invoices (Ostuarved)**: Upload invoice files and maintain internal information. | Partial | API notes shipped; evidence storage service only, no upload (FA §§6,13). |
| **Vendor invoices (Ostuarved)**: Filter purchase invoices as all, periodised or not periodised (Periodiseeritud / Periodiseerimata); periodisation setup itself was not captured. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendor invoices (Ostuarved)**: Create purchase invoices. | Have | Draft creation, review submission and approval through UI/API (FA §6). |
| **Vendor invoices (Ostuarved)**: Filter by unpaid or overdue status. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendor invoices (Ostuarved)**: Filter date ranges using invoice date, posting date, due date or creation date. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendor invoices (Ostuarved)**: Export lists as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendor invoices (Ostuarved)**: Configure displayed fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendor orders (Ostutellimused)**: Create purchase orders. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Filter by date range and status. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Track draft, sent/pending, confirmed, rejected, other, ordered, partially received and received statuses. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Represent invoice, sales invoice and purchase invoice creation through statuses. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Expose a delivery-information action (Tarneinfo). | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Configure numbering and whether amounts appear on purchase-order PDFs. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Use purchase-order document and email templates. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Export lists as PDF, XLS or CSV. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Vendor orders (Ostutellimused)**: Configure displayed fields and download attachments in bulk. | n/a | Purchase orders outside the product boundary; integrate a sister product (FA §17). |
| **Pending documents and e-invoices**: Provide a pending purchase invoices inbox (Ootel ostuarved) with a date-range filter; processing controls were absent from its empty capture. | Partial | Draft/review bills shipped, not imported-document inbox/date filtering; SA processing controls unobserved (FA §6). |
| **Pending documents and e-invoices**: Import XML purchase invoices conforming to the Estonian e-invoice standard. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Pending documents and e-invoices**: Upload XML through drag-and-drop or file selection. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Pending documents and e-invoices**: Import from an invoice centre starting from a selected date. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Pending documents and e-invoices**: Require users to open imported invoices, check data and save, according to import guidance. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Pending documents and e-invoices**: Receive digitised purchase invoices and receipts through the integrations in section 11. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Create and open vendor records. | Have | Supplier contacts created/listed/selected through UI/API, no edit route (FA §3). |
| **Vendors (Hankijad)**: Maintain name, registration number, VAT registration number, group, address and contacts. | Partial | Name/registration/VAT/address/email shipped; groups and broader editing absent (FA §3). |
| **Vendors (Hankijad)**: Manage vendor groups through a linked page. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Import and export vendor master data. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Import opening balances through an opening-invoices action. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Export lists as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Sort identifying columns and configure displayed fields. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Vendors (Hankijad)**: Download attachments in bulk. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Create and open item records. | Partial | Product/service defaults, tax and price service only; no item maintenance route (FA §13). |
| **Articles / items (Artiklid)**: Distinguish goods (Kaup), services (Teenus) and stock items (Laoartikkel). | Partial | Products/services service only; stock items need external inventory (FA §§13,17). |
| **Articles / items (Artiklid)**: Filter by type and active purchase/sales usage. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Maintain code, description, unit, VAT treatment, sales eligibility/price and purchase eligibility/price. | Partial | Product/service defaults, tax and price service only; no item maintenance route (FA §13). |
| **Articles / items (Artiklid)**: Display creation time and creator. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Import and export item master data. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Export lists as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Sort item columns and configure displayed fields. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Download attachments in bulk. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |
| **Articles / items (Artiklid)**: Provide pre-populated items for common expenses, fixed asset purchases, domestic/EU sales, exports, exempt sales and opening balances. | Missing | No equivalent routed capability established (FA §§3,6,13,17). |

### 3. Payments

Source: SA §3, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| Select client or vendor context when entering bank/cash payments. | Partial | Reviewed matches/splits cover bank-document allocation, not the full manual bank/cash form or balance/column controls (FA §§7,13). |
| Maintain payment account, date, currency and source document, with account balance displayed. | Partial | Reviewed matches/splits cover bank-document allocation, not the full manual bank/cash form or balance/column controls (FA §§7,13). |
| Filter outstanding documents and display reference number, due date, currency, unpaid amount and payment amount columns. | Partial | Reviewed matches/splits cover bank-document allocation, not the full manual bank/cash form or balance/column controls (FA §§7,13). |
| Enter a client advance-payment amount in the captured client context. | Missing | No equivalent routed capability established (FA §§7,17). |
| Add/delete additional payment rows with description, quantity, price, amount, account and object. | Missing | No equivalent routed capability established (FA §§7,17). |
| Display total payment amount and save payment records. | Partial | Reviewed matches/splits cover bank-document allocation, not the full manual bank/cash form or balance/column controls (FA §§7,13). |
| Maintain a cash payment order number (Order nr). | Missing | No equivalent routed capability established (FA §§7,17). |
| Create and expose edit actions for bank payments (Pangamaksed). | Partial | Reconciliation creates payments; direct entry service only, no payment edit action (FA §§7,8,13). |
| Filter bank payments by account and date range. | Missing | No equivalent routed capability established (FA §§7,17). |
| Include a netting account (Tasaarveldus) among bank-payment account choices. | Missing | No equivalent routed capability established (FA §§7,17). |
| Add an opening balance for an advance payment. | Missing | No equivalent routed capability established (FA §§7,17). |
| Export bank-payment lists as PDF, XLS or CSV. | Missing | No equivalent routed capability established (FA §§7,17). |
| Configure displayed bank-payment fields. | Missing | No equivalent routed capability established (FA §§7,17). |
| Provide a bank-payment import workspace (Pangamaksete import) for payments awaiting saving. | Have | Imported transactions await explicit reconciliation; import alone does not post (FA §7). |
| Distinguish imported-but-unsaved payments from saved payments in the empty-state guidance. | Have | Imported transactions await explicit reconciliation; import alone does not post (FA §7). |
| Configure import settings and export imported payment data. | Missing | No equivalent routed capability established (FA §§7,17). |
| Expose import from the bank-payment list; bank file formats and upload controls were not captured. | Have | CSV/CAMT.053 uploads shipped; SA formats unconfirmed (FA §7). |
| **Automation:** import new LHV/Coop transactions with a delay of a few hours. | Partial | Open-banking primitives only, planning stub, no wired consent/feed/reconnect/worker; no shipped named gateway (FA §16). |
| **Automation:** import the previous day's SEB/Swedbank transactions daily. | Partial | Open-banking primitives only, planning stub, no wired consent/feed/reconnect/worker; no shipped named gateway (FA §16). |
| Export payment orders (Maksekorralduste eksport) through a selection screen with a next-step action. | Missing | No equivalent routed capability established (FA §§7,17). |
| Filter candidates by date range, due date or file-created date. | Missing | No equivalent routed capability established (FA §§7,17). |
| Filter for valid bank accounts and records without a payment order. | Missing | No equivalent routed capability established (FA §§7,17). |
| Show the selected payment-order total in EUR. | Missing | No equivalent routed capability established (FA §§7,17). |
| Create and expose edit actions for cash payments (Kassamaksed). | Missing | No equivalent routed capability established (FA §§7,17). |
| Filter cash payments by cash account and date range. | Missing | No equivalent routed capability established (FA §§7,17). |
| Export cash-payment lists as PDF, XLS or CSV and configure fields. | Missing | No equivalent routed capability established (FA §§7,17). |

### 4. General ledger

Source: SA §4, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| Select currency when entering a journal entry. | Have | Journal API accepts currency/balanced lines; no workspace journal form (FA §8). |
| Add/delete journal rows with account, debit, credit, description and object. | Partial | API account/debit/credit/description lines; no row UI or objects (FA §8). |
| Display separate debit and credit totals; validation of balance is not demonstrated. | Partial | Balanced-entry validation shipped; no form totals because no journal UI (FA §8). |
| Upload journal attachments through drag-and-drop/file selection and maintain internal information. | Partial | Evidence storage service only; no journal upload (FA §13). |
| Save journal entries through the form. | Partial | Journal API shipped; no entry form (FA §8). |
| Create ledger entries (Pearaamatu kanded / Kanded). | Have | Journal API accepts currency/balanced lines; no workspace journal form (FA §8). |
| Filter entries by currency and date range. | Partial | GL date filter shipped; currency entry-list filtering absent (FA §8). |
| Enter opening balances through a dedicated action. | Partial | Journal API can record opening balances; no dedicated action/import (FA §§8,17). |
| Export entries as PDF, XLS or CSV. | Partial | GL browser print/save PDF; CSV service only, no XLS or entry-list export (FA §§8,13). |
| Configure entry fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Generate a general ledger report (Pearaamat) for a selected period. | Have | GL report with date range and voucher/account/contact data (FA §8). |
| Select multiple accounts and multiple objects. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Filter the general ledger by currency. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Choose whether printed output shows related accounts. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Choose whether to show only accounts with transactions. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Export general ledger output as PDF, XLS or CSV. | Partial | GL browser print/save PDF; CSV service only, no XLS or entry-list export (FA §§8,13). |
| Generate account turnover / trial balance (Käibeandmik), described as account turnover by day. | Partial | Trial balance shipped; daily turnover not established (FA §8). |
| Select its period, accounts and objects. | Partial | Trial-balance dates shipped; selected-account/object controls absent (FA §8). |
| Select EUR or EEK in the captured turnover report. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Optionally group report days. | Missing | No equivalent routed capability established (FA §§8,13,17). |
| Export turnover output as PDF, XLS or CSV. | Partial | Browser print/save PDF, no routed XLS/CSV (FA §8). |

### 5. Reports

Source: SA §5, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Principal financial reports**: Generate a balance sheet (Bilanss) at a selected date. | Have | Balance sheet as at date and P&L for period shipped (FA §8). |
| **Principal financial reports**: Generate an income statement (Kasumiaruanne) for a selected period. | Have | Balance sheet as at date and P&L for period shipped (FA §8). |
| **Principal financial reports**: Generate a cash flow statement (Rahavoogude aruanne) for a selected period. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Choose simple reports or comparisons with preceding months, financial years, days, quarters or manually selected periods. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Compare objects in income and cash flow statements; this option is absent from the captured balance-sheet selector. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Use quick comparisons for years, year-to-date, adjacent months and the same month in the previous year. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Optionally display accounts within financial reports. | Partial | Account data in reports shipped; optional show/hide controls unconfirmed (FA §8). |
| **Principal financial reports**: Export the three principal reports as PDF, XLS or CSV. | Partial | Balance sheet/P&L browser printing only; no cash-flow/server PDF/XLS/CSV suite (FA §8). |
| **Principal financial reports**: Compose annual-report balance sheet and income statement data (Majandusaasta aruanne). | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Select micro-enterprise, small-enterprise OÜ or small-enterprise AS forms. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Select a configured financial-year period. | Partial | Report dates/seeded fiscal periods exist; no annual-report year selector (FA §§2,8). |
| **Principal financial reports**: Download annual-report data as XBRL, according to the page guidance. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Principal financial reports**: Derive annual-report values from account/report-row mappings and report configuration. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Sales invoice list (Müügiarvete nimekiri):** invoices within a specified period. | Partial | Invoice list shipped; specified-period report/export not established (FA §4). |
| **Full catalogue from `/et/reports`**: **Unpaid client invoices (Klientide tasumata arved):** unpaid invoices as at a specified date. | Partial | Ageing/as-at filter shipped, but current paid totals rather than historical allocations (FA §8). |
| **Full catalogue from `/et/reports`**: **Client statement of account (Saldoteatis):** generate a statement-of-account PDF. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Cash report (Kassaaruanne):** cash-account statement between selected dates. | Partial | Account net-movement cash summary, not a full cash-account statement (FA §8). |
| **Full catalogue from `/et/reports`**: **Item sales report (Artiklite müügiaruanne):** item sales during a specified period. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Sales turnover by day (Müügikäive päevade lõikes):** aggregate daily invoices and display a chart. | Partial | Six-month invoiced-revenue chart, no daily turnover chart (FA §12). |
| **Full catalogue from `/et/reports`**: **Sales by client (Müük klientide lõikes):** invoices within a specified period, under this client-oriented title. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Sales margins (Müügimarginaalid):** margin report; correct goods margins require inventory accounting. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Sales margins by invoice (Müügimarginaalid, arvepõhine):** invoice-based margin report. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Periodic client statement (Kliendi väljavõte, perioodiline):** combine sales invoices and bank/cash payments. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Client advance payments (Klientide ettemaksed):** include only payment advance rows; direct account entries and additional payment rows are excluded. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Item sales margins (Artiklite müügimarginaalid):** margins from period sales invoices; stock items use FIFO cost, other items use purchase/sales price differences. Remaining description is truncated. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **VAT report (Käibemaksuaruanne):** VAT report, for example for completing a MOSS declaration. | Partial | VAT/KMD workpapers and VD detail shipped; no country/MOSS sales report (FA §9). |
| **Full catalogue from `/et/reports`**: **Item turnover by month (Artiklite müügikäive kuude lõikes):** monthly item sales turnover within a period. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Receipts with sales invoice object (Laekumised müügiarve objektiga):** invoices paid during the period with invoice-object information. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Item sales summary (Artiklite müügi koondaruanne):** aggregate item sales. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Purchase invoice list (Ostuarvete nimekiri):** purchase invoices within a specified period. | Partial | Bill list shipped; specified-period purchase report/export not established (FA §6). |
| **Full catalogue from `/et/reports`**: **Unpaid vendor invoices (Hankijate tasumata arved):** unpaid invoices as at a specified date. | Partial | Ageing/as-at filter shipped, but current paid totals rather than historical allocations (FA §8). |
| **Full catalogue from `/et/reports`**: **Vendor statement of account (Hankija saldoteatis):** generate a statement-of-account PDF. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Item purchase report (Artiklite ostuaruanne):** purchases during a specified period. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Purchases by vendor (Ost hankijate lõikes):** invoices within a specified period, under this vendor-oriented title. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Periodic vendor statement (Hankija väljavõte, perioodiline):** combine invoices and bank/cash payments for a selected vendor. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Vendor advance payments (Hankijate ettemaksed):** include only payment advance rows; direct account entries and additional payment rows are excluded. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Item purchase summary (Artiklite ostu koondaruanne):** aggregate item purchase invoices. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Quotes (Pakkumised):** client quotes made within a specified period. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Items in orders (Artiklid tellimustes):** items ordered during the period. | n/a | Order/inventory reports outside product boundary; external integration needed (FA §17). |
| **Full catalogue from `/et/reports`**: **Orders (Tellimused):** client orders prepared within a specified period. | n/a | Order/inventory reports outside product boundary; external integration needed (FA §17). |
| **Full catalogue from `/et/reports`**: **Created / amended entries (Sisestatud / muudetud kanded):** entries created/amended within the selected period, restricted to those created/amended after 19 March 2016. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Object report (Objekti aruanne):** object-related income, expenses, assets and liabilities. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Entries with counterparty details (Kanded koos teise osapoole andmetega):** period entries with client/vendor name and registration number. | Partial | GL includes contact information, not established registration-number report (FA §8). |
| **Full catalogue from `/et/reports`**: **Fixed asset report (Põhivaraaruanne):** acquisition cost, depreciation and carrying value for a period. The catalogue has no corresponding link; `fixed_assets_report.txt` captures `/et/showreport/fixedassetdepreciations`. | Missing | No equivalent routed capability established (FA §§8,17). |
| **Full catalogue from `/et/reports`**: **Warehouse movements during a period (Laoliikumised perioodil):** movement quantities within a selected period. | n/a | Order/inventory reports outside product boundary; external integration needed (FA §17). |
| **Full catalogue from `/et/reports`**: **Annual-report assistance (Majandusaasta aruande abi):** supporting report for annual-report notes. | Missing | No equivalent routed capability established (FA §§8,17). |

### 6. Taxes

Source: SA §6, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| Create and list Estonian VAT returns (Käibedeklaratsioonid / KMDd). | Partial | KMD/tax codes are shipped subsets; full schedules/KMD INF, special treatments and editable mappings absent (FA §§2,9,17). |
| Export VAT-return lists and exposed report output as PDF, XLS or CSV. | Partial | Reviewed KMD CSV/browser printing shipped, no statutory list PDF/XLS suite (FA §9). |
| Configure displayed VAT-return fields. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Create and list TSD declarations (TSDd), supported by payroll payout-code mappings. | Partial | TSD preparation/review/XML/transitional CSV uncommitted, resident-only and not e-MTA verified (FA §16). |
| Export TSD lists as PDF, XLS or CSV and configure fields. | Partial | TSD preparation/review/XML/transitional CSV uncommitted, resident-only and not e-MTA verified (FA §16). |
| Send tax declarations directly through the Tax and Customs Board integration. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Select VAT-return versions KMD1 to KMD6 by captured effective-date ranges from 2000 onwards. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Configure additional formulas per return row (Rea lisavalem). | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Represent standard/reduced/zero-rated transactions, intra-EU sales/acquisitions, exports, imports, exempt turnover, special reverse-charge transactions and adjustments in return settings. | Partial | KMD/tax codes are shipped subsets; full schedules/KMD INF, special treatments and editable mappings absent (FA §§2,9,17). |
| Distinguish deductible input VAT for imports, fixed assets, fully business-used passenger cars and partly business-used passenger cars. | Partial | KMD/tax codes are shipped subsets; full schedules/KMD INF, special treatments and editable mappings absent (FA §§2,9,17). |
| Configure total VAT, VAT payable and overpaid VAT rows. | Partial | VAT totals/payable calculated; no row-formula editor (FA §9). |
| Maintain default VAT treatments with percentages, Estonian/English/Russian labels, codes, sales/purchase columns and KMD annex A/B mappings. | Partial | KMD/tax codes are shipped subsets; full schedules/KMD INF, special treatments and editable mappings absent (FA §§2,9,17). |
| Provide captured 0%, 5%, 9%, 13%, 20%, 22% and 24% rates, including historical treatments. | Partial | EE 24/13/9/0 codes shipped; historical EE 20/22/5 catalogue unconfirmed (FA §2). |
| Provide reverse-charge, vehicle 100%/50%, fixed asset, exempt, excluded-from-KMD, triangulation, import VAT and KMS § 41.1 treatments. | Partial | KMD/tax codes are shipped subsets; full schedules/KMD INF, special treatments and editable mappings absent (FA §§2,9,17). |
| Add company VAT rates with percentages, multilingual names, ordering, sales/purchase accounts and codes. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Copy company VAT rates from another associated company. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Require additional VAT-return settings for company-specific rates to flow into KMD automatically. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Bulk replace selected item, client, vendor and recurring-invoice default VAT rates. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Replace 22% with 24% for ordinary, reverse-charge, vehicle 100%/50%, fixed asset and KMS § 41.1 variants. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| **Automation:** replace immediately or automatically in the early morning of 1 July 2025, the specific historical option captured; arbitrary scheduling is not shown. | Missing | No equivalent routed capability established (FA §§2,9,17). |
| Save and confirm bulk replacement selections. | Missing | No equivalent routed capability established (FA §§2,9,17). |

### 7. Warehouse

Source: SA §7, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| Create warehouse movements (Laoliikumised). | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Filter movements by warehouse and date range. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Optionally include purchase/sales movements in the list. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Export movement lists as PDF, XLS or CSV, configure fields and download attachments in bulk. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Generate stock-on-hand reports (Laoseisude aruanne) by warehouse, date, object and selected items. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Optionally include zero-quantity items. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Generate movement reports by warehouse, period, item and object. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Create warehouses (Laod) and include inactive warehouses in the list. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Import opening stock balances or corrections to stock levels. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Export a correctly formatted stock file for import. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Configure comma/tab/semicolon column separators and single/double quotation text delimiters. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Set the date of generated movements. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| **Automation:** create incoming/outgoing movements for changed stock quantities in an import. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Transfer between warehouses using a separate file row for each warehouse. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Preserve quantities for item/warehouse combinations omitted from the file. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Require existing items before stock import, with a link to item import. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Use FIFO cost for stock-item sales margins, explicitly stated in the report catalogue; wider costing settings were not captured. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |
| Configure default warehouse and movement date through parameters. | n/a | Warehouse/inventory explicitly outside product boundary; integrate a sister product (FA §17). |

### 8. Fixed assets

Source: SA §8, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| Create fixed asset records (Põhivarad). | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Expose an asset purchase action (Osta). | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Filter by asset group and optionally include inactive assets. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Export asset lists as PDF, XLS or CSV, configure fields and download attachments in bulk. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Create depreciation records (Amortiseerimised). | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Export depreciation lists as PDF, XLS or CSV and configure fields. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Report acquisition cost, depreciation and carrying value for a selected period. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Filter reports by assets and asset groups. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Export asset reports as PDF, XLS or CSV. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Set depreciation periods to month, quarter or year. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| **Automation:** enable automatic depreciation (Amortiseeri automaatselt). | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Configure impairment/write-off expense and asset sales accounts. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Add/delete groups with Estonian/English names, depreciation percentage, asset, accumulated depreciation and expense accounts. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Provide groups for land, buildings, vehicles, computers/systems, other machinery/equipment, other tangible assets, goodwill, development expenditure, software, patents/licences/trademarks and other intangible assets. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |
| Expose account-creation links beside asset settings. | Missing | No fixed-asset register, depreciation or asset-reporting module (FA §17). |

### 9. Payroll

Source: SA §9, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Workers, absences and salaries**: Create workers (Töötajad) and optionally display inactive workers. | Partial | Employee create/edit/active state shipped in EE EUR demo; inactive-list display unconfirmed (FA §10). |
| **Workers, absences and salaries**: Query worker data from the Pension Centre (Küsi andmeid Pensionikeskusest) through a batch action. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Workers, absences and salaries**: Export workers as PDF, XLS or CSV, configure fields and download attachments in bulk. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Workers, absences and salaries**: Create leave/absence records (Puhkused/puudumised). | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Filter absences by worker, type and date range. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Display a three-month calendar with previous/next navigation and current-month shortcut. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Show public holidays for the period. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Show calendar/working-day totals with calendar-day columns labelled for holiday inclusion/exclusion. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Expose a salary-opening action from the absence page. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Workers, absences and salaries**: Create pay records (Töötasud). | Have | Monthly draft runs/results/approval/posting shipped, 2026 demo only (FA §10). |
| **Workers, absences and salaries**: Filter pay by year, month, worker, payout type and date range. | Partial | Monthly run list/inspection, no full worker/payout/date filters (FA §10). |
| **Workers, absences and salaries**: Export pay as PDF, XLS or CSV and configure fields. | Partial | Payslip PDF shipped, no pay-list XLS/CSV/field configuration (FA §10). |
| **Workers, absences and salaries**: Provide payslip (Palgaleht) email templates with payroll year/month placeholders; generation/bulk sending controls were not captured. | Partial | Payslip PDF download, no payslip email-template/send workflow (FA §10). |
| **Calculator (Palgakalkulaator)**: Calculate with employer cost, gross pay or net pay as the selected basis. | Partial | Gross/hourly input calculates net/cost; no net-to-gross or cost-input calculator (FA §10). |
| **Calculator (Palgakalkulaator)**: Select captured calculator years 2023, 2024, 2025 and 2026. | Partial | 2026 payroll only, no 2023-2025 calculator (FA §10). |
| **Calculator (Palgakalkulaator)**: Switch between employment-contract and management-board remuneration settings. | Have | Monthly/hourly versus board-fee basis, minimum exemption reasons and pension settings shipped (FA §10). |
| **Calculator (Palgakalkulaator)**: Configure application of the minimum monthly social-tax basis. | Have | Monthly/hourly versus board-fee basis, minimum exemption reasons and pension settings shipped (FA §10). |
| **Calculator (Palgakalkulaator)**: Configure retirement-age status and tax-free income. | Partial | Tax-free choice shipped; pension-age unemployment handling incomplete (FA §§10,17). |
| **Calculator (Palgakalkulaator)**: Configure employer and employee unemployment insurance contributions. | Partial | Supported pay-basis contributions/taxes calculated, not editable payout-type switches (FA §10). |
| **Calculator (Palgakalkulaator)**: Select funded-pension contributions of 2%, 4% or 6%. | Have | Monthly/hourly versus board-fee basis, minimum exemption reasons and pension settings shipped (FA §10). |
| **Wage reports and TSD data**: Produce a leave-day summary (Puhkusepäevade koondaruanne) aggregating workers' leave balances; this is the only report visible on the wage-reports page. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Wage reports and TSD data**: Map payout types to TSD, TSD A1 EE and TSD A1 foreign codes in payroll settings. | Partial | Resident semantic TSD work uncommitted; official-code/non-resident suite absent (FA §16). |
| **Wage reports and TSD data**: Use separate non-resident employment/holiday-pay types and mappings. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Wage reports and TSD data**: Create/export TSD declarations through Taxes; a separate detailed wage or TSD-data report was not visible. | Partial | Resident semantic TSD work uncommitted; official-code/non-resident suite absent (FA §16). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure payout-type treatment for income tax, social tax, funded pension and unemployment insurance. | Partial | Supported pay-basis contributions/taxes calculated, not editable payout-type switches (FA §10). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure leave-day accrual and participation in holiday-pay calculations. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure whether payout types appear on worker cards. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Assign payout formulas and expense accounts. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure TSD mappings and a part-time/workload field (Osakoormus). | Partial | FTE shipped, TSD mappings uncommitted/limited (FA §§10,16). |
| **Payroll settings (Palgaarvestuse seaded)**: Expose account-creation actions for payout expense accounts. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Add company-specific payout types with description, settings, two tax groups, leave and TSD configuration. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide employment pay (Tööleping), using an amount-excluding-absences formula and captured code sequence 10 / 11 / 12. | Partial | Employment/board fees shipped; absence formulas/official TSD suite not shipped (FA §§10,16,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide sick pay (Haigushüvitis), code 24. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide management-board remuneration (Juhatuse liikme tasu), codes 21 / 22 / 23. | Partial | Employment/board fees shipped; absence formulas/official TSD suite not shipped (FA §§10,16,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide work/service-contract remuneration (Töövõtu- või käsundusleping), code 17. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide redundancy compensation (Koondamishüvitis), codes 33 / 34 / 35. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide rent/licence fees (Rendi- ja litsentsitasud), code 50. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide additional pay (Lisatasu), codes 10 / 11 / 12. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide other non-taxable pay (Muu maksustamata tasu), without a displayed TSD code. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide holiday pay (Puhkusetasu), codes 10 / 11 / 12. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide study-leave pay (Õppepuhkuse tasu), codes 10 / 11 / 12. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide paternity-leave pay (Isapuhkuse tasu), code 16. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide birth allowance within the income-tax exemption (Sünnitoetus), code 14. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide other income-tax-only payments (Muu väljamakse, ainult TM), code 16. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide workplace accident/occupational disease compensation (Tööõnnetus- või kutsehaigushüvitis), code 32. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide agricultural-land rent (Rent, põllumajandusmaa), code 56. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide remuneration paid by an individual (Füüs. isiku poolt makstud tasu), codes 18 / 19 / 20. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide deductions (Kinnipidamised), without a displayed TSD code. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide child-care leave pay (Lapsepuhkuse tasu), code 16. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide leave pay for parents of disabled children (Puudega lapse vanema lapsepuhkuse tasu), code 16. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide non-resident employment pay (Tööleping, mitteresident), with the amount-excluding-absences formula and codes 120 / 122 / 121. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide non-resident holiday pay (Puhkusetasu, mitteresident), codes 120 / 122 / 121. | Missing | No equivalent routed capability established (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure absence types by description, formula and associated payout type. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Configure whether absence types are ignored in all calculations or deducted from leave days. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Add company-specific absence/leave types with formulas, payout types and settings. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide annual leave using six-month average calendar-day pay. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide annual leave preserving the last salary. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide unpaid leave, unpaid caring/sickness leave and other unpaid absences. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide sick leave using an average-pay sickness-certificate formula linked to sick pay. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide paid study leave using an average-pay study-leave formula. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide unpaid study leave separately. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide pregnancy/maternity leave. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Retain paternity leave labelled through 30 June 2020, using average working-day pay. | n/a | Legacy leave explicitly ends in 2020/2022; historical reconstruction outside audited 2026 demo scope (FA §10). |
| **Payroll settings (Palgaarvestuse seaded)**: Retain child-care leave labelled through 31 March 2022, using minimum working-day pay. | n/a | Legacy leave explicitly ends in 2020/2022; historical reconstruction outside audited 2026 demo scope (FA §10). |
| **Payroll settings (Palgaarvestuse seaded)**: Retain leave for parents of disabled children labelled through 31 March 2022, using average working-day pay. | n/a | Legacy leave explicitly ends in 2020/2022; historical reconstruction outside audited 2026 demo scope (FA §10). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide an informational absence type (Info). | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide non-resident annual leave using six-month average pay, linked to non-resident holiday pay. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide non-resident annual leave preserving salary, linked to non-resident holiday pay. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |
| **Payroll settings (Palgaarvestuse seaded)**: Provide care leave on a daily-rate basis (Hoolduspuhkus päevamäära alusel), using minimum working-day pay and linked to child-care leave pay. | Missing | No leave/absence accounting or calendar workflow; general HR belongs in a sister product (FA §§10,17). |

### 10. Settings/admin

Source: SA §10, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Profile and permissions**: Maintain first name, surname, contact telephone and Estonian/English language preference. | Partial | Registration name and EE/EN language shipped; profile name/phone editor absent (FA §§1,12). |
| **Profile and permissions**: Change username/email and password. | Partial | Password reset shipped; username/email editor absent (FA §1). |
| **Profile and permissions**: Link or continue with Google. | Have | Configured Google sign-in/email association (FA §1). |
| **Profile and permissions**: Link or continue with Facebook. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Activate MFA; its authentication method is not shown. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Display the user's last visit timestamp. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Open documents in editable mode by default. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Warn when closing documents with unsaved changes. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Select the company/access role activated after login. | Partial | Switcher remembers browser company, no editable default company/access role (FA §§1,2). |
| **Profile and permissions**: Upload a personal profile picture. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Add/open company users with username/email, name and group. | Partial | Role invitations/acceptance via API, no general user-admin view (FA §1). |
| **Profile and permissions**: Filter active users or include inactive users. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Display access periods and last login times. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Add/open permission groups (Kasutajagrupid). | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Profile and permissions**: Provide Administrator (Administraator) and Standard user (Tavakasutaja) groups with names/descriptions; a granular permission matrix was not captured. | Partial | Fixed owner/admin/accountant/approver/viewer permissions, no editable groups (FA §1). |
| **Company administration**: Add/open companies and show name, registration number, user group and creation date. | Partial | Company create/list/registration, not full group/creation-date admin surface (FA §2). |
| **Company administration**: Switch companies through the shared header. | Have | Workspace company switcher shipped (FA §2). |
| **Company administration**: End the current user's company rights. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Begin company deletion or expose deletion within company details. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Maintain company name, registration number, VAT number, address and contacts. | Partial | Name/registration/API VAT at creation; no profile/address/contact editor (FA §2). |
| **Company administration**: Display the income-statement scheme, captured as Scheme 1. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Maintain email, telephone, fax, website, Skype, other contact details, contact person and postal address. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Choose contact details shown on invoices. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Upload company logos in JPG/GIF/PNG below 300 kB, with recommended 600 × 300 px JPG dimensions. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Company administration**: Display current/previous month ledger-entry counts. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Accounts**: Add/open chart-of-accounts records (Kontoplaan). | Partial | Read/select seeded chart, no account maintenance (FA §2). |
| **Accounts**: Filter assets, liabilities/equity, income and expense accounts. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Accounts**: Maintain codes/descriptions and balance-sheet/income-statement/cash-flow row mappings. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Accounts**: Sort/paginate accounts, configure fields and export PDF/XLS/CSV. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Accounts**: Configure default item purchase, sales and inventory accounts. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Accounts**: Configure receivables, other operating income and client advance accounts. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Accounts**: Configure payables, other operating expenses, vendor advances and additional inventory cost accounts. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Accounts**: Configure payment accounts for foreign-exchange gains/losses, conversion fees, cash deposits/withdrawals, money in transit, additional rows when there is no debt and bank fees. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Accounts**: Configure current-year profit/loss and retained earnings accounts. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Accounts**: Configure output VAT, VAT prepayments, VAT payments and input VAT accounts. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Accounts**: Configure payroll accounts for wages payable/expense, social tax payable/expense, unemployment insurance payable/expense, personal income tax, funded pension and deductions. | Partial | Country account defaults seeded, no customer default-account configuration (FA §2). |
| **Document templates (Dokumendimallid)**: Automatically save default template settings, according to the notice. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Toggle item code and combined code/description line. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Toggle signature line, object, contact person, client balance, registration number, period and bank accounts. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Configure row-heading and total-block background colours. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Configure heading, document-header, row-header and total-block text colours. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Set separate additional text for invoices, quotes and orders, with save controls. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Select invoice bank accounts through payment settings. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Use company logos on PDFs; show company name when no logo is uploaded. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Add company templates and filter by active status/document type. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Apply templates to invoices, quotes, client orders and purchase orders. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Provide captured Estonian/English templates for all four types and Russian templates for invoices, quotes and client orders. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Document templates (Dokumendimallid)**: Display template creation time and creator. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Emails (E-kirjad)**: Add/edit templates with name, subject, content and active document association. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Emails (E-kirjad)**: Provide invoice, reminder, purchase order, quote, payslip and client-order templates. | Partial | Fixed recurring/reminder delivery shipped, no editable document/payslip catalogue (FA §5). |
| **Emails (E-kirjad)**: Use substitution fields including document number and payroll year/month. | Partial | Fixed recurring/reminder delivery shipped, no editable document/payslip catalogue (FA §5). |
| **Emails (E-kirjad)**: Choose general or external SMTP servers. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Emails (E-kirjad)**: Choose company or user email for replies. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Emails (E-kirjad)**: Configure sender name and reply email address. | Partial | Deployment Postmark/From settings, no company sender/reply editor (FA §5). |
| **Emails (E-kirjad)**: Configure an EveryPay payment-link button in email templates. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Maintain an object's class, name and active flag, and save its record. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Add/open balance-sheet, income-statement and cash-flow report rows. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Define row content from account balances or formulas referring to other row codes. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Organise headings and calculated totals. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Show rows always or only when non-zero. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Export report settings as PDF/XLS/CSV. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Add/open countries with code, name and EU membership. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Copy countries from another associated company. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Add/open financial years (Majandusaastad) with year, date range and active status. | Partial | Fiscal start/seeded periods, no year editor/active controls (FA §2). |
| **Reports and reference data**: Make submitted financial years inactive to prevent changes, as annual-report guidance recommends. | Partial | Locked-period enforcement shipped; lock_period service only, no close/reopen/date UI (FA §§8,13). |
| **Reports and reference data**: Add objects (Objektid) and include inactive objects. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Reports and reference data**: Use objects as analytical dimensions in ledger, financial, stock, debt and sales-receipt reports; separate project-management workflows are not shown. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Payment methods and VAT**: Add/edit bank accounts with description, IBAN, SWIFT, ledger account, currency and invoice-display flag. | Partial | Create/read bank accounts with currency/IBAN/ledger link, no edit/SWIFT/display flag (FA §7). |
| **Payment methods and VAT**: Add/edit cash accounts with description, ledger account and currency. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Payment methods and VAT**: Add/edit payment methods with description, ledger account and cash/non-cash designation. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Payment methods and VAT**: Provide cash, accountable-person, card-sales and card-purchase methods. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Payment methods and VAT**: Configure netting alongside bank accounts. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Payment methods and VAT**: Maintain VAT-return formulas, company/default VAT rates and bulk replacement, detailed in section 6. | Partial | Read tax codes/prepare workpapers; no rate/formula maintenance/replacement (FA §§2,9). |
| **Parameters (Parameetrid)**: Configure a transaction locking date. | Partial | Locked-period enforcement shipped; lock_period service only, no close/reopen/date UI (FA §§8,13). |
| **Parameters (Parameetrid)**: **Automation:** enable automatic exchange rates. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Parameters (Parameetrid)**: Default new document dates to today. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Parameters (Parameetrid)**: Configure invoice/order/quote filenames using company/client/document-number placeholders. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Parameters (Parameetrid)**: Enable six-decimal-place VAT calculations on sales documents. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Parameters (Parameetrid)**: Configure separate invoice, credit note, quote, client-order and purchase-order number patterns with year/sequence placeholders. | Partial | Separate default invoice/credit sequences, no pattern editor or orders (FA §2). |
| **Parameters (Parameetrid)**: Configure invoice reference type/length, late interest and payment terms. | Partial | Contact terms/API reference, no reference-type/length/interest editor (FA §§3,4). |
| **Parameters (Parameetrid)**: Configure quote validity and client-order payment terms. | n/a | Order/warehouse parameters outside product boundary (FA §17). |
| **Parameters (Parameetrid)**: Choose purchase-order PDF amount visibility. | n/a | Order/warehouse parameters outside product boundary (FA §17). |
| **Parameters (Parameetrid)**: Default movement dates to today and select the default warehouse for invoices/movements. | n/a | Order/warehouse parameters outside product boundary (FA §17). |
| **Parameters (Parameetrid)**: Configure separate client/vendor statement-of-account default texts. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Identify counterparties without related transactions for cleanup. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Delete unlinked clients/vendors with an explicit non-restorable deletion warning. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Generate/delete client payment reference numbers in bulk. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Count clients with/without reference numbers. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Gate generation on a configured compatible reference type; invoice-based numbering prevents generation. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Maintenance, services and devices**: Activate connected services through the settings area described in section 11. | Partial | Connection/config/test/disconnect shipped, not SA provider catalogue (FA §11). |
| **Maintenance, services and devices**: Add devices (Seadmed); types and behaviour are absent from the empty capture. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Billing**: Select STARTER usage-based billing, priced by purchased entry volume. | n/a | Vendor-specific packages/prices are not transferable bookkeeping needs; no equivalent FA billing backend established (FA §12). |
| **Billing**: Select PRO unlimited-use monthly billing. | n/a | Vendor-specific packages/prices are not transferable bookkeeping needs; no equivalent FA billing backend established (FA §12). |
| **Billing**: Show snapshot prices: STARTER from €0.16 per entry plus VAT; PRO €13.50 per month plus VAT during a promotion, then €27.00. These are not verified current prices. | n/a | Vendor-specific packages/prices are not transferable bookkeeping needs; no equivalent FA billing backend established (FA §12). |
| **Billing**: Configure invoice-recipient name, registration/VAT numbers, email and address. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Billing**: Assign billing-recipient managers from associated company administrators. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Billing**: End billing-recipient management rights. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |
| **Billing**: Provide a billing-invoices area gated on selecting a billing method; invoice-history details were not shown. | Missing | No equivalent routed capability established (FA §§1,2,12,17). |

### 11. Connected services

Source: SA §11, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **SmartAccounts e-invoice sending service:** send without receiving; monthly subscribers send free, usage-based companies pay one entry per invoice, and receipt requires an Omniva contract. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Finbite, formerly Omniva invoice centre:** send e-invoices and deliver purchase invoices into SmartAccounts. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Estonian Tax and Customs Board (Maksu- ja Tolliamet / EMTA):** submit tax declarations directly. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Shopify:** move online-shop data into SmartAccounts; entities are not specified. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **LHV Connect:** automatically deliver new bank transactions within a few hours after account selection and bank-contract activation. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **SEB Baltic Gateway:** automatically deliver the previous day's transactions daily following SmartAccounts and bank activation. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Swedbank Gateway:** automatically deliver prior-day transactions daily from the following day; activation uses accounts and a Gateway contract ID. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Coop Gateway:** automatically deliver new transactions within a few hours after bank approval and SmartAccounts activation. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **EveryPay / LinkPay:** invoice-email payment links using API username/key and link token after merchant onboarding and a successful test payment. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Scoro:** automatically reflect sales invoices, purchase invoices and payments in SmartAccounts. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Envoice:** deliver digitised purchase invoices and expense receipts. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Bilnex:** send/receive e-invoices including Peppol and transfer digitised PDF purchase documents. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Uku:** export purchase/sales invoice and entry counts for monthly accounting-service invoicing in Uku. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **CostPocket:** transfer digitised receipts/invoices for confirmation/correction and receive e-invoices; its app also offers mileage logs and expense/travel reports, without explicit transfer detail for each. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **WooCommerce:** connect the shop to accounting through a SmartAccounts plugin; individual transfers are not stated. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Saago:** listed workflow/property/equipment integration; the description explains Saago but does not specify synchronised entities. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **ShopRoller:** let the shop query stock and automatically reflect sales transactions in accounting. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Bidrento:** listed rental-property-management integration; synchronised entities are not specified. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Yester:** automatically import approved leave/absences and return leave/sickness-record updates to Yester. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Bouk:** reflect accommodation/service-booking sales in accounting. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Banqup:** deliver invoices/receipts digitally in real time regardless of original format or entry method. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **Microsoft Power BI, created by Future Finance:** extended reporting, consolidation, combining other data and external sharing; detailed scope is referred to the creator. | Missing | No shipped connector for this service; cards/primitives do not establish transfer support (FA §§11,17). |
| **API service:** custom integrations and a stated prerequisite for Envoice, WooCommerce and ShopRoller. | Partial | Public organisation-scoped API shipped, not SA connectors/general webhook-outbox delivery (FA §§1,13,15). |

### 12. Other

Source: SA §12, including its capture-file references. FA references appear per row.

| SmartAccounts capability | FastAccounts status | Notes |
| --- | --- | --- |
| **Debts and balances**: Report unpaid client/vendor invoices as at a selected date. | Partial | Ageing/as-at filters shipped, historical allocations absent (FA §8). |
| **Debts and balances**: Filter by invoice or posting date. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Debts and balances**: Select one currency or all currencies with EUR as base currency. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Debts and balances**: Filter by counterparty group, invoice object and selected counterparties. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Debts and balances**: Choose all unpaid or only overdue invoices. | Partial | Outstanding ageing/overdue invoice filtering, no equivalent debt-report toggle (FA §§4,8). |
| **Debts and balances**: Independently show/hide charts, invoices and advances. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Debts and balances**: Export debt reports as PDF/XLS/CSV. | Partial | Browser print/save PDF, no server PDF/XLS/CSV (FA §8). |
| **Debts and balances**: Generate client/vendor statement-of-account PDFs (Saldoteatis) with separate default texts. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Dashboard**: Offer quick creation links for sales invoices, purchase invoices, bank/cash payments and entries. | Partial | Invoice/bill creation and bank review; no manual cash/journal form (FA §§4,6,7,8,12). |
| **Dashboard**: Show numeric links for client debts, vendor debts, orders and quotes; all captured values are zero and dashboard visible text was not saved. | Partial | Overview AR/AP shipped; no quotes/orders counts (FA §12). |
| **Dashboard**: Link unpaid-client/vendor totals to detailed debt reports. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Dashboard**: Provide an income/expense chart-data link (Vaata andmeid → `chartdataincomeexpense`); its page and actual data were not captured. | Partial | Revenue/net-bank-movement chart, no equivalent income/expense data page (FA §12). |
| **Dashboard**: Show a multi-currency rate shortcut linked to the full currency table. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Dashboard**: Provide a getting-started checklist/deck with add, complete and enter actions (Lisa, Täienda, Sisesta) and a close action; exact task text is absent. | Partial | First-company onboarding shipped; exact SA task deck and FA equivalent unconfirmed (FA §12). |
| **Dashboard**: Show in-app news and mark items read (Loetud), including TSD-reporting and terms-of-use changes. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Dashboard**: Link to recent accounting activity. | Partial | Recent invoices/bank-review activity, not latest-100 creation/amendment identity feed (FA §12). |
| **Dashboard**: Show the latest 100 documents with source document, counterparty, amount, document date, creation timestamp/creator and amendment timestamp/editor. | Partial | Recent invoices/bank-review activity, not latest-100 creation/amendment identity feed (FA §12). |
| **Currencies, notifications and support**: Show currency code/name, European Central Bank rate (EKP kurss), inverse rate, absolute/percentage change and latest rate date. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Sort by code, ECB rate or rate date and open currency records. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Include historical currencies, BTC and Other in the catalogue; blank rates mean an automatic ECB feed is not established for every entry. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Select in-app/email newsletters independently. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Select notifications for Scoro automatic-import errors, automatic recurring invoice creation, automatic depreciation and automatic reminder creation. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Open the common-header notification/message bell. | Missing | No equivalent routed capability established (FA §§12,17). |
| **Currencies, notifications and support**: Use one account across companies with switching, company-specific user groups and a default post-login company. | Have | One account/scoped roles/remembered browser company cover switching (FA §§1,2). |
| **Currencies, notifications and support**: Switch application language between Estonian and English. | Have | EE/EN workspace language switcher shipped (FA §12). |
| **Currencies, notifications and support**: Access contextual help and external help materials. | Partial | EE/EN support guides shipped; contextual help unconfirmed (FA §14). |
| **Currencies, notifications and support**: Request support advice; captured text promises a reply no later than the next working day, without exposing all request fields. | Partial | Contact-page links, no request backend or next-working-day commitment (FA §12). |

## 5. Where FastAccounts is ahead

These are demonstrated strengths relative to captured evidence, not proof that SmartAccounts lacks equivalent hidden functionality.

- **Ranked, reviewed reconciliation:** shipped amount/reference/counterparty/date reasons, confirmation, split allocation and deduplicated imports (FA §7). SA §§3,11 establish automatic arrival into an import queue, not ranked matching or automatic posting.
- **Recurring worker with bounded catch-up:** shipped scheduled execution, duplicate protection, history and optional PDF email (FA §5). SA §1 explicitly describes manual batches; automatic scheduling controls remain unconfirmed.
- **Bill approval:** routed draft/review/role-authorised approval and posting (FA §6). SA §2's pending inbox is empty and approval controls unconfirmed.
- **Immutable balanced ledger:** atomic posting, idempotency, tenant checks, locked-period rejection and protected posted records (FA §§4,6,8). SA §4 shows totals but not balance enforcement/immutability. Generic reversal controls remain service only.
- **Reviewed employee intake:** staged file/FastHR records, matches, apply/reject and preserved unresolved work (FA §11), versus a different Yester leave integration in SA §11.
- **Evidence integrity foundation, Partial:** attachment hashes/ownership/retention methods are service only (FA §13), no routed upload/library. SA attachment controls are visible, so attachments are not a shipped parity advantage; backend integrity cannot be compared from UI text.

## 6. Caveats & unverified claims

### SmartAccounts evidence limits

- The inventory reads 79 text files, not linked help/screenshots. Additional captures appeared during its audit; joined vendor-debts/connected-services index records were read separately. Labels/actions do not prove execution, legal accuracy or reliability.
- Empty lists/unopened forms limit detail. Asset/warehouse/worker forms returned system errors; additional menu captures contain headings without contents. Pending-purchase processing, device behaviour and exact onboarding tasks remain unknown.
- Quote/order conversion rests on status vocabulary, not captured controls. Full credit-note behaviour, purchase periodisation setup, bank formats and totals-calculation scope are unconfirmed. Invoice M± is unexplained.
- Recurring generation has manual guidance and an automatic-creation notification hint, with scheduling/activation/dispatch unconfirmed. Reminder create/send switches are explicitly independent. Bank arrival populates unsaved imports, with posting/reconciliation automation unestablished.
- Receipt requires an Omniva contract. LHV/Coop describe hours, SEB/Swedbank prior-day daily delivery, with bank contracts/approval/representative involvement. These were not exercised.
- Journal totals do not prove balance enforcement or immutable history. Last visits/logins and document creation/amendment identities do not establish an immutable audit log. Dashboard headings/ageing/layout/chart data were not recovered from link-only/zero captures.
- MFA method/granular permissions are unknown. Personal names/pictures are not proven printed on invoices, while company logos/selected contacts are explicit. Auto-save notices coexist with save buttons, so uniform behaviour is unconfirmed.
- All 33 catalogue reports/23 services are represented without execution tests. Detailed wage/TSD reports were not visible beyond leave summary. Item-margin text is truncated. Advance reports count payment advance rows only, excluding direct/additional postings; stock margins explicitly use FIFO.
- Rates/codes/legacy leave/billing prices are snapshots, not current guidance. Checkbox states do not establish all enabled tax/leave treatments. VAT scheduling specifically names 1 July 2025, not arbitrary dates. Custom rates require KMD mappings; annual XBRL relies on report/account mappings and submitted-year inactivation guidance.
- Saago/Bidrento entities are unspecified, Shopify/WooCommerce limited by card text, Power BI third-party supplied. Wider CostPocket functions are not all proven transferred. Do not attribute external products' wider capabilities to SmartAccounts. Cleanup explicitly deletes unlinked counterparties irreversibly.

### FastAccounts evidence limits

- Shipped means committed implementation/routing, not deployed, provider-approved or accountant-accepted. The source audit did not start/seed/migrate/test the app or call providers. Static coverage is not production certification.
- **TSD is uncommitted (FA §16).** Review/export uses semantic resident Annex 1 mappings, snapshotted IDs and assumed month-end payment dates. Annex 2 is reserved. Official taxonomy/classification and manual e-MTA upload validation are pending. Transitional CSV limits assumed dates through 2027. XBRL GL XML does not imply accepted filing, direct submission is rejected.
- KMD is a subset, no full schedules/KMD INF/direct filing. UK boxes 2/8/9 are zero. Cash VAT weights current paid totals on document-date selections, not a full payment-period engine. VD lacks a separate filed/export lifecycle (FA §9).
- Invoice XML is review output, not verified schema/operator delivery, inbound processing or Peppol support. Direct HMRC/e-MTA filing, receipts/filed-period automation absent; HMRC/GoCardless primitives use planning stubs (FA §§4,16,17).
- Payroll is EE/EUR, 2026 demo, production UAT pending. Leave/sickness/benefits, salary pro-rating, certain minimum-social-tax reductions/relief and pension-age unemployment handling incomplete. No UK payroll/payment execution (FA §§10,17).
- Items, direct payments, evidence, manual email, generic reversals, lock management, close checks, retention and GL CSV are service only. API credits/journals are shipped despite absent dedicated workspace creation controls (FA §§4,8,13).
- Ageing uses current paid totals, not historical allocations. Browser printing differs from server PDFs. Currency fields do not prove FX conversion/revaluation; seeded defaults do not prove editable settings (FA §§2,8,17).
- QuickBooks/Xero/Merit tests are not accounting migration. Universal file import is employee-only; Personio/BambooHR partial, not shipped-provider totals. Synthetic demo connections do not prove live access (FA §§11,14,16,17).

Open questions: deployed revision; provider approval and production UK/EE accountant acceptance; TSD commitment/manual e-MTA acceptance; target segments requiring deliberately excluded inventory/orders.

## 7. Suggested next steps

- Build reviewed SmartAccounts migration for contacts, opening AR/AP and balanced opening journals, with duplicate checks/reconciliation totals, touching `import_service.py`, `documents.py`, `ledger.py`, `api_app.py` and `static/app.js`; employee import alone is insufficient.
- Wire selected Estonian bank consent/callback, scheduled imports, reconnect and failure review, touching `connectors/providers.py`, `connectors/registry.py`, `integration_service.py`, `banking.py`, `api_app.py` and `static/app.js`; preserve deduplication/explicit posting review.
- Validate outgoing EE XML and add operator delivery plus reviewed inbound purchase intake, touching `documents.py`, connectors, `integration_service.py`, `import_service.py`, routes and purchase views; retain source documents and delivery/receipt outcomes.
- Complete KMD/KMD INF and validate working-tree TSD against official upload requirements using synthetic accountant cases, touching `tax.py`, `payroll.py`, `tsd.py`, migrations/routes and tax/payroll views; then add EMTA authorisation, retry-safe submission and receipts.
- Add supplier payment-order selection/export, bank-detail validation and duplicate-export traceability, touching `documents.py`, `banking.py`, routes and bank/bill views; verify the bank-file format independently of execution support.
- Complete routine EE payroll leave/sickness calculations and reviewed sister-product absence inputs, touching `payroll.py`, employee/run routes, connectors, `import_service.py` and payroll views; test pro-rating/retirement/minimum-tax exceptions without adding general HR.
- Add explicit advance accounts/records and later allocation, touching `documents.py`, `banking.py`, `organisations.py`, `ledger.py`, additive migrations and reconciliation/report views; preserve balanced posting/reversal links.
- Generate client/vendor statement PDFs and historical periodic statements, touching `ledger.py`, `documents.py`, report routes and `static/app.js`; support selected dates and default texts.
- Add a bookkeeping fixed-asset register and deterministic depreciation worker, touching a new domain service, `ledger.py`, `organisations.py`, additive migrations/routes and accounting views; define impairment/disposal/reversal acceptance.
- Add cash-flow classifications, comparison periods and annual-report mappings/XBRL, touching `ledger.py`, `organisations.py`, report routes/migrations/views; keep the cash summary distinct from the statement.
- Expose evidence/items/locks/reversals/GL export, then scoped company/account/tax/series settings and MFA, touching `documents.py`, `governance.py`, `organisations.py`, `web/account_auth.py`, routes and workspace views; prioritise accountant controls before colours/cleanup.
- Validate quote demand and define sister-product order/inventory integration contracts through `integration_service.py`, connectors and reviewed import surfaces; keep stock/order management outside this repository, then prioritise bulk exports, template/reminder settings and VAT replacement for the chosen segment.
