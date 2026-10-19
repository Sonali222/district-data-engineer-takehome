# Business answers (source data through Day 2)

## Q1. Paid revenue in USD by segment: Q2 2026 vs Q2 2025

| Segment | Q2 2025 | Q2 2026 | Change | Change % |
|---|---:|---:|---:|---:|
| ENTERPRISE | $4,086,134.80 | $3,637,367.71 | $-448,767.09 | -10.98% |
| MID-MARKET | $3,562,948.38 | $2,626,957.55 | $-935,990.83 | -26.27% |
| SMB | $3,934,165.72 | $3,108,385.99 | $-825,779.73 | -20.99% |
| UNKNOWN | $255,987.72 | $234,547.87 | $-21,439.85 | -8.38% |
| UNMATCHED | $141,260.07 | $184,324.87 | $43,064.80 | 30.49% |

Q2 2026 is unchanged after Day 2 because the account segment changes are effective 2026-10-01, outside both comparison quarters. `UNKNOWN` means the CRM segment is blank/invalid; `UNMATCHED` means the invoice cannot be joined to a CRM account and is kept visible.

## Q2. Active customers

- **Finance:** 180 on Day 1; 179 after Day 2. Definition: distinct matched accounts with at least one paid invoice in Q3 2026. The decrease is caused by a Day 2 restatement changing an invoice from paid to refunded.
- **Sales:** 199 on Day 1; 199 after Day 2. Definition: distinct matched accounts with any non-void invoice in trailing 12 months (2025-10-01 through 2026-09-30).

## Q3. Median time-to-close for P1 tickets opened in 2026
**20.73 hours.** Only valid closed P1 tickets opened in calendar year 2026 are included; open tickets and impossible negative durations are excluded/quarantined.

## Q4. Top 10 accounts by paid revenue in trailing 12 months

| Account | Account ID | Paid revenue | Tickets opened in window |
|---|---|---:|---:|
| Black Mesa Telecom | ACC-00135 | $433,896.45 | 1 |
| Pied Piper Holdings | ACC-00293 | $431,284.20 | 2 |
| Zorg Systems | ACC-00307 | $418,066.51 | 5 |
| Vandelay Holdings Corp | ACC-00845 | $415,111.89 | 0 |
| Acme Systems | ACC-00264 | $412,225.67 | 4 |
| Nakatomi Logistics (Legacy) | ACC-00842 | $410,650.37 | 0 |
| Umbrella Labs | ACC-00218 | $409,295.40 | 1 |
| Duff Energy | ACC-00234 | $408,643.58 | 4 |
| Hooli Financial | ACC-00188 | $407,309.22 | 0 |
| Soylent Energy | ACC-00202 | $401,650.58 | 2 |

Window: 2025-10-01 through 2026-09-30. Ticket counts include tickets matched to the account and opened in the same window.

## Q5. Billed in H1 2025 with no paid/open invoice since 2026-04-01
**39 matched accounts** under the stated implementation. This is sensitive to the ambiguous meaning of “billed” and excludes unmapped billing references from account-level distinct counts; confirm the intended definition with RevOps.

## Q6. Day 2 impact on August and September 2026 paid revenue

| Invoice month | Before | After | Change | Paid invoice count before → after |
|---|---:|---:|---:|---:|
| 2026-08 | $3,253,438.90 | $3,207,370.66 | $-46,068.24 | 161 → 159 |
| 2026-09 | $1,383,165.85 | $1,518,019.74 | $134,853.89 | 71 → 78 |

The before/after totals are independently recomputed from source files, applying v2 records by `legacy_id` for restatements and `id` for new invoices. August declines because two invoices were restated from paid to non-paid. September increases because ten invoices changed from non-paid to paid and three paid invoices changed to non-paid; the net effect is positive. New invoices in this delivery are dated in October. Refunds are excluded from paid revenue in their invoice month.

## Q7. Paid revenue by segment for October 1–4, 2026

| Segment at invoice date | Paid revenue |
|---|---:|
| ENTERPRISE | $434,759.40 |
| MID-MARKET | $280,474.58 |
| SMB | $173,372.91 |
| UNKNOWN | $14,770.07 |
| UNMATCHED | $8,800.00 |

Segments use the effective-dated account history; Oct 1 reclassifications are applied to October invoices. `UNMATCHED` revenue is shown separately rather than silently omitted.
