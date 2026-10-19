# Meridian AI Data Engineer Take-Home

A reproducible, local-first implementation of the District Technologies take-home. Python's standard library and SQLite are used so a reviewer can run the pipeline without cloud credentials or an API key. SQLite is the lightweight queryable store; a production version could swap in DuckDB/Postgres behind the same modeling conventions.

## Setup and run

Requires Python 3.10+; no third-party packages required.

```bash
python src/pipeline.py day1
python src/pipeline.py tests
python src/pipeline.py report
python src/pipeline.py day2                 # intentionally stops at schema approval gate
python src/pipeline.py day2 --approve-schema-v2
python src/reconcile_day2.py
python -m unittest discover -s tests -v
python evals/run_agent_evals.py
python src/agent.py "How many active customers?" --llm  # optional live smoke test; requires GEMINI_API_KEY or OPENAI_API_KEY
```

Run Day 1 first and preserve `outputs/meridian.db`; Day 2 is incremental. `--approve-schema-v2` is a deliberate human gate after reviewing `docs/schema_v2_mapping.md`. Re-running Day 2 upserts by stable invoice key and produces the same modeled invoice state; the load report's action counts naturally differ on a replay because already-seen records are now updates/deduplications.

## Architecture and model

```text
Source files -> raw_rows (immutable payload + file/row/load/hash)
             -> schema checks + quarantine
             -> accounts + account_history (effective-dated segments)
             -> invoices (one row per canonical invoice_id; USD amount; source lineage)
             -> tickets (one row per ticket; reviewed account match + confidence)
             -> fx_rates -> deterministic metric/tool functions -> agent responses
```

| Table | Grain / key | Notes |
|---|---|---|
| `raw_rows` | one source row per `(load_id, source_row)` | Original payload, source path, hash, load time |
| `accounts` | one current row per `account_id` | Current CRM attributes |
| `account_history` | one account segment version per `(account_id, valid_from)` | Day 2 segment changes effective Oct 1, 2026 |
| `account_map` | one source account ID | Duplicate-name candidates are unapproved for review; no silent name-based merge |
| `invoices` | one canonical invoice per `invoice_id` | Native amount/currency, status/date, USD, source file/row, original reference |
| `tickets` | one ticket per `ticket_id` | Fuzzy candidate accepted only at >=0.90 similarity; lower-confidence tickets stay unmatched |
| `fx_rates` | one currency/month | Invoice-month conversion rate |
| `quarantine` | one rejected source row | Source payload and reason |
| `load_report` | one source file/load ID | Received/loaded/updated/deduplicated/quarantined counts |
| `metrics` | one metric definition | Central metric definitions |

## Business answers

`outputs/day1_answers.json` contains questions 1–5; `outputs/day2_answers.json` includes question 7. Run `python src/reconcile_day2.py` for question 6, independently aggregated from the source exports. Q2 returns both definitions: Finance = at least one paid invoice in Q3 2026; Sales = any non-void invoice in trailing 12 months (2025-10-01 through 2026-09-30). Do not report one number without naming its definition.

Important qualifications:

- Missing FX rates cause affected invoice rows to be quarantined rather than silently valued at 1.0. Revenue outputs include `UNMATCHED` where a billing record cannot be linked to a CRM account and `UNKNOWN` where the CRM segment is blank/invalid.
- The source's ambiguous slash dates are interpreted as US month/day/year because the export includes values such as `08/20/2026` that cannot be day-first. This is an explicit source convention assumption; production should confirm it with the vendor.
- Account names alone do not prove that two records are the same entity. Duplicate CRM names are review candidates; the canonical `account_id` is not automatically collapsed.
- Ticket matching is intentionally conservative. Similarity scores below 0.90 remain unmatched for human review. A production matcher should use a reviewed alias table and evaluate precision/recall on labeled examples.
- Q5's exact business interpretation is under-specified: this implementation counts distinct matched account IDs billed in H1 2025 that have no paid/open invoice on or after 2026-04-01. The question could mean any invoice in H1 or only paid invoices; ask RevOps to confirm.

## Data issues found

1. **Duplicate invoice IDs (18 duplicate rows in the raw file):** detected by business key; first occurrence retained, duplicates counted and not inserted twice.
2. **Billing references are mixed:** integers, `C###`, and `ACC-#####`; normalize formats to `ACC-#####`. IDs absent from CRM remain visible as unmatched rather than dropped.
3. **FX coverage gaps:** a non-USD invoice with no currency/month rate is quarantined with the missing rate in the reason; do not guess an FX rate.
4. **CRM duplicate names:** four duplicate-name groups. They are flagged in `account_map` as unapproved review candidates, not merged solely on a matching name.
5. **Segment normalization:** capitalization variants standardized; blank/unknown values represented as `UNKNOWN`, not imputed.
6. **Ticket priority variants:** `sev1`–`sev4` mapped to `P1`–`P4`; invalid values quarantined.
7. **Ticket entity matching:** manually entered organization names often differ from CRM names. Conservative similarity matching is used; low confidence stays unmatched.
8. **Ticket timestamp issues:** impossible negative durations are quarantined; open tickets have null duration and are excluded from median time-to-close.
9. **Day 2 schema drift:** billing v2 nests account/amount and renames fields, changes amount from cents to major units, and uppercases status. Mapping is documented and requires explicit approval.
10. **Restatements:** use `legacy_id` to update an existing invoice, not count it as new revenue; `id` is used for new rows when legacy ID is absent.
11. **CRM segment reclassification:** Day 2 snapshot changes are recorded as SCD Type 2 with effective date 2026-10-01 so historical Q2 reports use historical segment values.
12. **Missing vendor guarantees:** the v2 timestamp is treated as update ordering, but vendor monotonicity is unconfirmed; production should preserve immutable invoice events and use a documented source version/cursor.

## Agent and evaluation

`src/agent.py` implements an LLM-backed tool-calling loop (`--llm`) over four allowlisted functions. The model chooses tools, but all aggregation is performed in parameterized SQL/Python; SQLite connections are read-only, the loop is capped at five rounds, the question length is capped, and each tool result carries provenance. Gemini is preferred when `GEMINI_API_KEY` is set; OpenAI-compatible configuration is also supported. API calls use a 30-second timeout and retry transient 429/5xx failures at most three times with bounded backoff. Do not commit secrets. The older keyword-based router remains only as a backward-compatible regression helper and is not the LLM agent.

Run `python evals/run_agent_evals.py` for the agent-level eval suite. The LLM response layer is mocked for reproducibility, while the real governed tools and read-only SQLite database execute. The cases cover direct questions, rephrasings, both active-customer definitions, ambiguity, a Day 2 affected metric, refusals, prompt-injection resistance, unsupported metrics, tool routing, and provenance. Expected numeric baselines are fixed outside the eval run in `tests/golden_answers.json`; Q6 is independently reconciled from source exports by `src/reconcile_day2.py`. Data-layer/unit results and agent-eval results are reported separately in `outputs/`.

**Failure mode not caught yet:** a plausible but incorrect fuzzy ticket-to-account match above the 0.90 threshold can inflate account-level support counts while passing structural tests. Add a manually labeled match evaluation set and precision monitoring before relying on those metrics.

## Part 4 / Part 5 / execution log

- Production memo: `docs/design_memo.md`
- PR #87 review: `docs/pr_review.md`
- Day 2 schema mapping approval record: `docs/schema_v2_mapping.md`
- Walkthrough: `docs/walkthrough.md`
- Time log and assumptions: `docs/time_log.md`

## AI coding tool use

AI assistance was used to scaffold code, identify data edge cases, draft tests, and organize the review/memo. All data findings were checked by running scripts against the supplied synthetic files. The implementation and outputs should be walked through and independently verified before submission; do not claim a test passed unless it was run locally.
