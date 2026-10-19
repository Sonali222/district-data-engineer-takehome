# PR #87 review

## Blocks merge

1. **[Security] Credentials are hard-coded.** The DB URL includes a production-looking password and the API key is embedded in source. Remove them from the diff, rotate any real credentials, and load secrets from the runtime secret manager/environment. Never commit live credentials.
2. **[Correctness] SQL is built by interpolating source values.** A customer-controlled invoice field can break the query or inject SQL. Use parameterized statements and explicit transaction handling.
3. **[Correctness] Exceptions are swallowed.** `except Exception: pass` silently loses malformed, duplicate, and failed rows, while the run reports success. Quarantine each bad row with a reason, fail the batch on contract-level errors, and publish reconciliation counts.
4. **[Correctness] Date watermark is not an incremental cursor.** Filtering `invoice_date > last_run_date` misses late-arriving invoices and restatements to old invoices; `set_watermark()` stores today's date rather than a source update cursor. Use a source change/version cursor where supported, plus invoice-key upserts and a replayable lookback/backfill policy.
5. **[Correctness] Inserts are not idempotent or restatement-safe.** Plain `INSERT` causes duplicate-key failures and cannot update older invoice statuses/amounts. Use a stable business key (`legacy_id` for v2 restatements) and transactional upserts with source-version ordering.
6. **[Safety / schema governance] The LLM mapping is applied without validation or approval.** Temperature 0.7 and raw sample rows make mapping nondeterministic and risk sending customer data externally. Generate a proposed mapping offline, validate exact coverage/types/uniqueness and sample transformations, require a human approval, and never send raw customer data to an external model by default.
7. **[Correctness] `flatten()` can overwrite fields and is not a schema contract.** Nested names such as `id` are ambiguous, missing fields are not checked, and `rows[0]` fails for empty input. Define a versioned deterministic mapping and validate every row before any writes.
8. **[Correctness] Revenue mart is created once and never refreshed.** `CREATE TABLE IF NOT EXISTS ... AS SELECT` leaves stale totals after subsequent loads, doesn't convert currencies, and doesn't implement invoice restatements. Use a view or rebuild/upsert the affected partitions transactionally using canonical USD values.
9. **[Reliability] Connection and transaction handling are unsafe.** The code commits each row, never closes cursor/connection, and can leave partial batches. Use context managers, batch transactions, rollback on failure, and only advance checkpoints after successful commit.
10. **[Correctness] Date parsing is ambiguous and may return `None`.** The format list includes both day-first and month-first without a source-level rule. Establish the vendor convention, reject ambiguous inputs when not specified, and test boundary dates.

## Should fix soon

- Validate allowed statuses, currency codes, positive/valid amounts, required fields, and foreign-key coverage before publishing.
- Add unique business-key constraints, load IDs, source file/row lineage, quarantine tables, and per-file reconciliation.
- Add tests for empty files, duplicate IDs, late arrivals, restatements, schema drift, malformed dates, missing FX, and rerunning the same batch twice.
- The SQL currently sums native `amount` across currencies. Convert to USD using the invoice-month FX rate and document refunded-invoice treatment.
- The watermark state is a local text file and can be lost or raced by concurrent runs. Store checkpoints transactionally in the database or orchestrator.
- Restrict DB credentials to least privilege and use read/write roles appropriately.

## Matter of taste

- `psycopg2` is fine if Postgres is the agreed store; otherwise isolate the adapter behind a small repository interface.
- Consider moving field mappings and schema versions into a reviewed configuration file rather than expanding the loader function.

## Highest-value automated checks

A CI integration test that loads a fixture twice, then applies a late restatement and asserts identical row counts plus the expected changed revenue would catch the idempotency/watermark/mart defects together. Pair it with a static secret scan and a lint/security gate that rejects string-interpolated SQL. Schema-contract tests should reject a new export before any data writes and require explicit approval of a reviewed mapping.
