# Billing schema v2 mapping — human review required

Detected by the top-level shape change from `invoices` to `data`, and row fields changing from flat keys to nested objects. The proposed mapping below was inspected against the sample and the full file before use; apply only with `--approve-schema-v2`.

| v2 source | Canonical field | Transformation |
|---|---|---|
| `legacy_id` | `invoice_id` | Use for an existing invoice/restatement when non-null |
| `id` | `invoice_id` | Use only for newly created invoices with no `legacy_id` |
| `account.id` | `customer_ref` | Normalize `ACC-####` to CRM account ID |
| `amount.value` | amount in major units | Parse decimal string; unlike v1, not cents |
| `amount.currency` | `currency` | Uppercase ISO code |
| `state` | `status` | Lowercase and validate against paid/open/void/refunded |
| `issued_on` | `invoice_date` | Parse ISO date |
| `updated_at` | update ordering | Only a record with an equal/newer update timestamp can replace existing state |

`account.display_name` is descriptive only; it is not used as a join key. `legacy_id` is the critical restatement key. Three duplicate/stale rows and one invalid/missing-FX row were deduplicated/quarantined in the current load report; inspect `quarantine` for exact row-level reasons.

Known limitation: the source's `updated_at` is used as a deterministic ordering field but no vendor guarantee about monotonicity was provided. Production should retain each source version in an immutable invoice-event table and apply a vendor-defined sequence/version if available.
