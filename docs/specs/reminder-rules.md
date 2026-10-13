# Organisation reminder rules

P1 item 13, 12 October 2026. Small organisation-owned configuration for the
existing automatic invoice reminder ladder. Email subject, body and PDF delivery
remain hard-coded through the established document sender.

## Defaults and shape

The actual existing ladder is stage 0 at three days before the due date, stage 1
at seven days overdue and stage 2 at fourteen days overdue. Without a row in
`reminder_rules`, selection and sending retain these exact timings and gates.
The migration seeds no rows and GET never creates a row.

`0024_reminder_rules.sql` adds one row per organisation with an enabled flag,
stage 1 and 2 day offsets, an optional stop stage and update timestamp. It uses
portable, rerunnable SQL and needs no PostgreSQL substitution. Stage 0 stays
fixed at -3 days; the two overdue offsets must be integer days satisfying
`1 <= stage 1 < stage 2 <= 14`. Both offsets are required even when the ladder
stops earlier. Stage identifiers match the existing numeric ladder, not custom
names. No free-form stages or templates are accepted.

PUT accepts this complete configuration, with extra fields forbidden:

```json
{"enabled": true, "stages": {"1": 3, "2": 10}, "stop_stage": 1}
```

`enabled` must be a JSON boolean. Offset strings, booleans, fractions, zero,
negative values, equal/reversed offsets, values beyond fourteen days, missing
or unknown stages and invalid stop stages are rejected without a write.
`stop_stage` is null, 0, 1 or 2. Null retains all three stages. A stop is inclusive:
1 permits stage 0 and 1, while 0 permits only the pre-due notice. Disabled rules
produce no automatic candidates.

## API, persistence and selection

GET and PUT live at `/organisations/{organisation_id}/reminder-rules`. All book
roles, including viewers, can read. Only owners and administrators can PUT,
with the existing CSRF dependency. Non-members cannot access another book.
Responses include `configured` and the effective stage/day pairs for preview.

Thin routes delegate validation and the transaction to `ReminderRuleService`.
`ReminderRuleRepository` owns parameterised organisation-scoped queries. A save
locks the organisation using the existing database convention and upserts its
single row. The existing `audit()` helper records `reminder_rules.updated` with
the actor and complete configuration in the same transaction.

`AutomationService.reminders_due` reads the effective ladder once per book.
It preserves invoice opt-outs, unpaid issued/part-paid eligibility, contact
tenant joins, stage event history and target-date comparison. Catch-up still
selects each eligible stage, and existing attempted/sent event handling remains
unchanged. Configuration changes do not reset or delete events. Stops filter
stage numbers without requiring earlier stages to have succeeded. Explicit
single-reminder sends retain their existing behaviour; these rules configure
automatic selection. No accounting posting or money calculation changes.

## Workspace and checks

A Settings Reminders view contains a compact card with an enable checkbox,
labelled overdue day inputs, stop-after select, save button and saved effective
preview. Viewers see disabled controls. The recurring/reminders table now shows
the actual configured overdue offset from the candidate target date. Copy is
appended in a trailing `reminder_rules` section and merged by `APPEND_SECTIONS`
in English, Estonian, Lithuanian and Latvian. Existing catalogue values remain
unchanged; Estonian follows the existing `meeldetuletus` terminology.

`tests/test_reminder_rules.py` covers default date boundaries and sends, changed
offsets, every inclusive stop, disabled rules, invoice opt-outs/status gates,
strict validation, roles, 401/403, CSRF, tenant isolation, audit upserts and raw
migration reruns. Send tests reuse the guarded `HTTP_CLIENT_FACTORY` and
`httpx.MockTransport` fixture from bulk sending. Offline Playwright checks cover
save/preview, owner/viewer controls and mobile containment in all four locales.
Full pytest and `node --check static/app.js` are required before delivery.

## Deferred scope

Configurable pre-due timing, horizons beyond fourteen days, additional stages,
template/subject editing, retry changes, production accountant UAT and live
PostgreSQL execution remain follow-ups. No environment configuration or new
dependency is introduced.
