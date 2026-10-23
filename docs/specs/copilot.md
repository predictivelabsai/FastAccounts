# AI copilot (Grok)

Date: 2026-10-13. Parity slate extension requested after P2 item 5.

## Goal

A Grok-powered assistant inside the workspace that can answer questions about
the organisation's data, summarise and explain reports and documents, scan
uploaded documents, and prepare staged imports from document content. The
copilot assists; it never writes accounting data on its own authority.

Provider: xAI Grok API, OpenAI-compatible
(`https://api.x.ai/v1/chat/completions`, bearer key, models such as
`grok-4-1-fast-reasoning`, usage token counts in the response). A dedicated API key is
carried in `FASTACCOUNTS_GROK_API_KEY` so usage is tracked per product.
An organisation may override the environment key using encrypted settings.
Keys never enter the repository,
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
   drawer explains unavailability for other roles when disabled, and every call
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
6. No secrets in prompts or client responses. Key material remains server-side; prompts contain org data and document text.
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
   capped; provider failure yields a clear error. Interrupted chat text is retained
   as a retryable assistant reply, never as an executable stage proposal.

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

Multi-conversation folders, tool/function calling that
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
  returns text plus usage. Key supplied by the service from encrypted organisation settings or env.
- `copilot_repository.py`: org-locked writes for org toggle, messages,
  usage counters; reads for history/usage. Reuses `audit`.
- Migration `0029_copilot` (additive, rerun-safe): `copilot_messages`,
  `copilot_usage`, `organisations.copilot_enabled`. Migration 0033 adds encrypted provider settings; CI + tests count 33.
- API routes in `api_app.py` (thin): POST/GET messages, POST scan,
  POST stage, GET usage, GET documents (picker), GET/POST settings (including the org toggle).
- SPA: a retractable right-side copilot drawer on every authenticated workspace
  feature page, opened by a labelled floating button. It has no navigation entry
  or standalone page. Escape or the close button closes it; focus moves inside
  on opening and returns to the opener on closing. Narrow screens use full width
  and reduced-motion preferences disable the slide animation.
  Ctrl+/ on Windows/Linux or ⌘/ on macOS toggles the drawer using the same
  focus and lazy-loading paths, including while typing in the composer. It is
  inactive without a selected organisation or while a `.dialog` modal is open.
  The toggle exposes `aria-keyshortcuts`; toggle and close tooltips include the
  platform shortcut. A muted, dismissible translated tip under the description
  appears on first opening without taking focus. Showing it immediately records
  `fastaccounts_copilot_shortcut_hint_seen` in localStorage; guarded storage
  access falls back to showing it at most once per page load.
  The transcript, composer with one attachment picker, stage proposal buttons
  and quota notices remain available. A collapsible administration section holds
  the organisation enable toggle, access grants/revocations by email and usage
  summary, visible only to owners/administrators. Page navigation preserves the
  drawer and draft; switching organisation clears its state.
  Messages accept an optional `page` navigation key (1-64 lower-case ASCII
  letters, digits, underscores or hyphens, starting with a letter). It is added
  as navigation context in the user prompt, within the existing 8,000-character
  text cap. It grants no authority and introduces no machine effects. Quotas,
  routes and the human-reviewed staging/commit boundary remain unchanged.
  Drawer copy lives in the `copilot` locale section in all four languages.
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
## 2026-10-21: Chat interaction and provider errors

The drawer uses a column layout with a scrolling, live message list and a pinned,
auto-growing composer. User messages use right-aligned accent bubbles; assistant
replies use plain text with a small copilot label. Timestamps remain in titles;
per-message token counts are hidden. Three translated suggestions send a first
question. The paperclip opens the existing document picker; the selected document
appears as a removable chip. Enter sends, Shift+Enter adds a newline, and empty
or in-flight sends are disabled. Inactive copilot states disable the composer.

Sending appends the question immediately, clears the composer and shows three
typing dots. The POST response replaces the pending reply without reloading the
drawer or showing a success toast. Failures show an inline retry button and restore
the question and attachment. Opening and sending scroll to the newest message.
Stage proposals remain available beneath assistant replies. A header settings
button toggles administration outside the message flow. Mobile width, reduced
motion, keyboard shortcuts and the first-open shortcut hint remain supported.

The default model is `grok-4-1-fast-reasoning`; `FASTACCOUNTS_GROK_MODEL` still
overrides it. Provider 401/403 responses report a rejected configured API key;
other HTTP failures retain the generic provider error. `CopilotProviderError`
returns HTTP 502 with a JSON `detail`. The service persists the same error as an
assistant message with zero tokens and no stage before re-raising. Existing quota
accounting is unchanged. Tests inject the HTTP client and never call a live provider.
New transcript messages use microsecond timestamps so a fast failure reply stays
after its question when the conversation is reopened.

## 2026-10-23: Organisation provider settings

Owners and administrators can POST an organisation xAI key and optional model
from drawer administration. Omitted keys are retained; an empty key clears the
organisation override. GET settings return only `configured` and `model`.
Migration 0033 stores credentials encrypted with the existing CredentialVault
and its key version, using the same portable DDL for SQLite and PostgreSQL.
The organisation key takes precedence for chat and scans; the environment key
remains the fallback. The global flag and organisation opt-in remain mandatory.
Settings audits contain a configuration flag, never a key.

## 2026-10-23: Streamed replies and formatted chat

POST `/copilot/messages` negotiates SSE with `Accept: text/event-stream`;
requests without that header retain the JSON path. Both use the same eager
prompt preparation, context, access checks and caps. Quota checks, organisation
opt-in and access rechecks, capacity reservation and the user message write run
under one organisation write lock before any provider request. The reservation
prevents parallel streams from bypassing daily limits. Pre-text failures release
it, retain the existing zero-token assistant failure and remain retryable; partial
replies count once. Prompt characters measure the composed JSON, capped at 280k.

The injectable HTTP client sends `stream=true` with usage inclusion and parses
SSE delta events, including usage-only events and split UTF-8 transport chunks.
Only assistant text is forwarded, never reasoning or provider error bodies. The
2048-token, 60-second and reply length caps remain. The browser receives `delta`
events with `{text}`, followed by `done` with the existing reply object and
`retryable`, `error` and `quota_consumed` metadata. The assistant row, usage totals
and completion audit are written in one transaction before `done` is emitted.
Provider errors and closed iterators retain partial text with an interruption
note and suppress stage extraction. Retry metadata on transcript reads comes
from scoped completion audits, without changing the stored transcript schema.
Unknown token totals for an interrupted stream remain zero, never estimates.

The drawer disables the composer during a send and renders deltas progressively.
A rejected streaming negotiation (404/405/406/415/501) retries using JSON. Older
servers returning JSON are consumed directly; browsers without readable streams
use JSON immediately. Quota, authentication and provider failures never trigger
an automatic duplicate send. Interrupted accepted streams offer explicit Retry.
Assistant prose uses a small escaped Markdown allowlist: emphasis, inline and
fenced code, simple lists and HTTP(S) links with `noreferrer` and a new tab.
Headings and raw HTML are disabled. Copy buttons retain the original reply text.
Controls, errors and interruption notes are translated in all four locales.

Offline validation covers encrypted settings, stream deltas/usage, provider
rejections, malformed/truncated/error streams, quota reservation, kill switches,
tenancy, completion audits, iterator closure, partial retry, browser streaming,
copy controls, sanitisation and both fallback paths. No live provider is used.

Wire-format reference: [xAI streaming documentation](https://docs.x.ai/developers/model-capabilities/text/streaming)
and [usage events](https://docs.x.ai/developers/cost-tracking). Integration tests
use only synthetic SSE through `httpx.MockTransport`, with an offline socket guard.
