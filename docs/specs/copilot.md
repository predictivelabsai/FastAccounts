# AI copilot (Grok)

Date: 2026-10-13. Parity slate extension requested after P2 item 5.

## Goal

A Grok-powered assistant inside the workspace that can answer questions about
the organisation's data, summarise and explain reports and documents, scan
uploaded documents, and prepare staged imports from document content. The
copilot assists; it never writes accounting data on its own authority.

Provider: xAI Grok API, OpenAI-compatible
(`https://api.x.ai/v1/chat/completions`, bearer key, models such as
`grok-4.7`, usage token counts in the response). A dedicated API key is
carried in `FASTACCOUNTS_GROK_API_KEY` so usage is tracked per product.
The key lives only in the environment and never enters the repository,
logs, audits or model prompts.

## Threat and abuse model (primary design driver)

Abuse of shared provider spend happened in the team's other products, so
defence in depth is mandatory:

1. Global kill switch. The feature is inert unless BOTH
   `FASTACCOUNTS_COPILOT_ENABLED=true` and a non-empty key are set. Missing
   or disabled makes every copilot endpoint return 404/409 respectively and
   the SPA shows the feature as unavailable.
2. Per-organisation opt-in. `organisations.copilot_enabled` (migration 0029)
   defaults to 0. Only owner/administrator can turn it on or off; the SPA
   hides copilot views for other roles when disabled, and every copilot call
   re-checks the flag server-side inside the org-locked read transaction.
3. Roles. All copilot routes require organisation membership. Chat reads and
   message sends are owner/administrator/accountant/approver/viewer;
   staging proposals into import batches and org settings writes are
   owner/administrator only, POST only, behind `require_csrf`.
4. Hard quotas, all enforced in one DB transaction BEFORE any provider call:
   - 30 messages per user per rolling 24h window; 200 per organisation per day.
   - 120k prompt characters per user per day; 800k per organisation per day.
   - 20 document scans per user per day; max 3 attachments per message; each
     PDF scanned by text extraction capped at 40 pages / 400k characters;
     images capped at 5 MB and PNG/JPEG only.
   - `max_tokens=2048` per request; provider timeout 60s; request body may
     not exceed ~280k characters total after composition.
   - Counters live in `copilot_usage` (per org/user/day) and `copilot_messages`.
     The daily org cap is the true cost ceiling and is checked again from the
     provider's returned usage before the quota row is written; calls that
     exceed it still count.
   - The `auth_rate_limits` idea is replaced by a direct 60s window count on
     stored messages (10 sends per user per minute), because copilot state
     lives in the organisation database while `auth_rate_limits` belongs to
     the account database.
5. Audit events. Every message send, scan and stage writes an
   `audit_events` row (`copilot.message`, `copilot.scan`, `copilot.staged`,
   `copilot.settings_updated`) with actor, model, token counts and truncated
   outcome. Owner/administrator can read a usage summary (GET
   `/copilot/usage`): per-user per-day messages/tokens so spend is visible.
6. No secrets in prompts or client responses. Only environment-provided key
   material exists server-side; prompts contain org data and document text.
7. Tenancy. Contexts are composed strictly from server-side services that
   take `organisation_id`; no cross-org joins, and attachments are validated
   with the existing org-scoped `evidence_download` integrity path.
8. Prompt injection. Document text and scanned OCR output are untrusted
   evidence. They are passed in delimited blocks marked as data with explicit
   instructions not to follow instructions found inside. Model output can
   produce exactly two machine effects, both human-reviewed: text into the
   chat transcript, and a staging proposal that a user must review and commit
   through the existing import pipeline. Nothing is posted, approved or
   reconciled by the model.
9. Content safety. Attachments are validated by type and size before any
   bytes leave the system; provider responses are time-limited and length-
   capped; provider failure yields a clear error, never a partial write.

## Capabilities (phase 1)

- Chat with data context: the send route composes a fixed system prompt plus
  server-computed, current org facts (name, currency, outstanding AR/AP totals
  and age buckets from `LedgerService`, unreviewed bank rows, quotes awaiting
  decision) with the user's message and (subject to message caps) recent
  conversation turns. Questions like "give me an overview" or "brief me on
  this month" are answered from these verified numbers.
- Report generation: where the user asks for a narrative, the same context
  includes the requested computed report JSON (P&L/balance sheet/trial
  balance/aging) from `LedgerService`; the model writes commentary, the
  numbers stay server-computed.
- Document scanning: `POST /copilot/scan {attachment_id}` reuses
  `evidence_download`. PDFs are extracted with `pypdf` to text; images are
  sent as base64 image parts for vision. Returns a summary plus an optional
  structured draft for the org's data.
- Staged imports: for contacts/items data in a document, the scan/chat
  reply may propose rows as CSV. Persisting the proposal (in the message row)
  and `POST /copilot/stage` routes it through `MasterDataImportService.stage`,
  producing an existing, reviewed, human-confirmed import batch. The stage
  call is rate-limited and audited; the Data import view remains the only
  commit path. The existing employee staging pipeline (integration file
  import) is a later extension.

## Non-goals (phase 1)

Streaming responses, multi-conversation folders, tool/function calling that
executes actions, rasterisation of PDF pages for vision (text-only extraction),
image generation, per-role custom quotas, per-user chat deletion, autonomous
actions on the ledger, sharing conversations across users.

## Limits table (defaults; not user-configurable in phase 1)

| Limit | Value |
| --- | --- |
| Message length | 8,000 characters |
| Reply cap | 2,048 tokens |
| Conversation turns sent | last 20 stored messages |
| Messages per user / org per day | 30 / 200 |
| Prompt characters per user / org per day | 120k / 800k |
| Scans per user per day | 20; images ≤ 5 MB; PDFs ≤ 40 pages |
| Provider timeout | 60 s |
| Burst limit | 10 sends/user/minute |

## Architecture

- `copilot.py`: `CopilotService` (gate checks, quota consumption, prompt
  composition, provider call through an injectable factory
  `HTTP_CLIENT_FACTORY`, response persistence, stage proposal handling).
- `copilot_provider.py`: the single place that knows the xAI wire format;
  returns text plus usage. Key read from env; never persisted.
- `copilot_repository.py`: org-locked writes for org toggle, messages,
  usage counters; reads for history/usage. Reuses `audit`.
- Migration `0029_copilot` (additive, rerun-safe): `copilot_messages`,
  `copilot_usage`, `organisations.copilot_enabled`. CI + tests count 29.
- API routes in `api_app.py` (thin): POST/GET messages, POST scan,
  POST stage, GET usage, GET documents (picker), PUT org toggle (settings).
- SPA: Copilot sidebar view (transcript, composer with one attachment picker,
  stage buttons, quota notices, owner/administrator enable toggle and usage
  panel in the view header; nav group assistant), locale section `copilot`
  appended via APPEND_SECTIONS with all four languages.
- `.env.sample` env documentation; deployment wiring (key) is a FastDevOps
  concern and must not be committed here.

## Validation plan

Offline tests with the transport injected through `HTTP_CLIENT_FACTORY` (no
live network; offline socket guard). Cover: kill-switch paths (no env / no
key / disabled org), quota and burst exhaustions (per user and per org),
prompt composition caps and delimiters, provider error and timeout paths,
scan PDF/text and image paths within caps, staging into the existing import
pipeline, tenancy isolation, role/CSRF matrix, audit rows with token counts,
usage summary, migration rerun, locale tail in all four languages and an
offline browser flow. Full `python -m pytest -q`; `node --check static/app.js`;
estnltk QA on all Estonian additions.