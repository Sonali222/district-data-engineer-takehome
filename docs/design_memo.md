# Production design memo: one data product, two deployment profiles

## Decisions

**Customer A — commercial SaaS.** Use the customer's existing cloud warehouse (Snowflake/BigQuery/Redshift as available), object storage for immutable raw files, and managed orchestration such as Dagster Cloud or the customer's native scheduler. Python/dbt-style transforms write tenant-scoped staging, core, and metric marts. Use a hosted frontier model only behind a tool-calling service; do not put raw exports into prompts. This optimizes time-to-value and minimizes operations cost.

**Customer B — air-gapped defense.** Ship the same versioned container images and SQL/Python transformation package into an approved on-prem environment. Use local object storage or encrypted filesystem for raw data, PostgreSQL or the approved local warehouse for modeled data, and an on-prem scheduler such as Airflow or systemd timers. Use a locally hosted model only if compute and authorization permit; the pipeline and deterministic metric tools must work with the model disabled. No telemetry, package downloads, or API calls at runtime; dependencies and model artifacts are staged, scanned, signed, and approved before transfer.

Keep one codebase by separating connectors, storage adapters, deployment configuration, and model provider behind interfaces. Pin dependency versions, use identical contract tests and fixtures in both profiles, and maintain environment-specific configuration rather than customer-specific branches. The tradeoff is that the air-gapped profile has slower upgrades and tighter compute limits.

## Change management and data correctness

Raw inputs are immutable and versioned by tenant/source/load ID. Contracts validate schema, types, accepted values, uniqueness, and required fields before transforms. A drift detector produces a proposed mapping and a sample diff; mappings that alter semantics, keys, currency units, or date interpretation require a human approval. Loads use stable business keys, source versions, idempotent upserts, explicit late-arrival windows, and replayable backfills. Restatements update current facts while preserving source-version history. Account segments use effective-dated history. A person must approve entity merges, semantic metric changes, new external data egress, and schema mappings that cannot be validated deterministically.

## Reliability target and response

Define reliability as a **weighted data contract score**, not model confidence: 30% correctness (sampled reconciliation to source and metric invariants), 25% completeness (expected rows and required fields), 20% join coverage (matched invoices/tickets), 15% freshness (source-to-mart lag), and 10% uniqueness/validity. Publish the components separately as well as the composite so a high score cannot hide a critical failure. The target is >90% for the relevant workflow, but key metrics also have hard floors (for example, no duplicate invoice business keys, no unapproved schema changes, and an explicit minimum join-coverage threshold). Track every load; alert and mark affected marts stale when thresholds fail; quarantine bad rows; block agent answers on stale or contract-breaking data; and offer the operator a replay/backfill path with an auditable diff.

## Security and audit

Every table and object path carries tenant identity and is protected by database roles plus row-level or schema-level isolation. Secrets come from the deployment's secret manager; rotate and scope them by service. Redact ticket subjects, org names, identifiers, and credentials from logs. The agent receives only approved aggregate/tool outputs, not unrestricted SQL or raw tables. For Customer B, audit logs record operator, artifact hash/version, input file hashes, mapping approvals, load IDs, metric definition versions, tool calls, row counts, and answer provenance; logs are tamper-evident and retained according to the customer's policy. Access to raw data and audit logs is separately controlled.

## AI layer and eval gates

For Customer A, use a hosted frontier model for intent parsing and tool selection, with all arithmetic in deterministic SQL/Python tools. For Customer B, use an approved local model if it meets task quality and hardware constraints; otherwise expose the same metrics through a non-LLM query interface. Every release runs data tests separately from agent evals, including paraphrases, ambiguous definitions, refusals, injection-like ticket text, and Day 2 restatements. Pipeline schema/metric changes and model/prompt changes are versioned; a change cannot deploy if contract tests, independently sourced expected answers, provenance checks, or refusal tests regress. Model quality never overrides failed data contracts.
