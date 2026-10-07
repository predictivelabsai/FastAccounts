# FastAccounts

Bookkeeping and small-business accounting for UK companies/sole traders and
Estonian OÜs/FIEs, with an accounting-bureau payroll module (Estonian rules)
for running payroll for client organisations.

## No AI attribution

Never add AI attribution anywhere in this repo: no "Co-Authored-By: Claude"
(or any other AI) trailer on commits, no "Generated with Claude Code" (or
similar) in PR descriptions, commits, or docs, and no AI tools listed as
contributors anywhere.

## Repo guidelines

Read `AGENTS.md` first: it carries the architecture rules (thin route
handlers, immutable balanced double-entry batches, `Decimal` for money,
tenant scoping, additive migrations), testing rules (pytest, no live network
calls), and the roadmap/change-log synchronization rule.