# Time log, assumptions, and cuts

## Time allocation (target: five hours)

- 0:30 — Read assignment, checklist, README, PR, and inspect file schemas.
- 0:45 — Profile duplicates, enum drift, references, FX coverage, and ticket matching.
- 1:45 — Implement raw lineage, contracts, normalization, core tables, history, metrics, and incremental load.
- 0:45 — Add agent tools and evaluation cases; execute tests and verify outputs.
- 0:35 — Draft design memo and PR review.
- 0:20 — README, reconciliation, walkthrough, and final verification.

## Assumptions

- Slash-form billing dates use US month/day/year; the data itself contains unambiguous examples such as `08/20/2026`.
- Day 2 account reclassifications take effect on 2026-10-01, per the assignment.
- `legacy_id` identifies existing invoice rows to restate; the v2 `id` identifies new invoices if `legacy_id` is null.
- Refunds remove the invoice from paid revenue in the invoice's own month.
- For active-customer counts, invoice date windows are inclusive of the start and exclusive of the next-day/period boundary.
- CRM account ID is the authoritative key. Duplicate names are not sufficient evidence to merge IDs.
- Ticket org matching uses a conservative similarity threshold, but still needs labeled precision/recall evaluation.

## Cut / next steps

- No production orchestrator, warehouse adapter, hosted/local LLM call, auth layer, or deployment manifests; the assignment prioritizes a scoped, runnable local implementation.
- The agent currently uses deterministic intent routing rather than an LLM. This makes the metric behavior auditable; an LLM can be added as a tool selector after eval coverage improves.
- Expected evals are small and include source-derived static baselines plus behavioral assertions; expand to an independently hand-calculated golden dataset for all seven questions.
- Add an immutable invoice-event table, source-version contract, exact schema/type validators for every file, and a labeled ticket/account alias set.
- Clarify Q5 wording with RevOps and clarify whether unapproved duplicate-account candidates should be merged after owner review.

## Questions I would ask

1. Should Q5 mean any invoice or only a paid invoice in H1 2025?
2. What source-side monotonic cursor/version is guaranteed for restatements in billing v2?
3. Can RevOps provide an approved CRM duplicate-account map and ticket-name alias list?
4. Should paid revenue round each invoice to cents before aggregation or round only the aggregate?
