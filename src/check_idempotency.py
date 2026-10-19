"""Run after Day 2; replays the same delivery and asserts modeled invoice state is unchanged."""
import json, sqlite3
from pathlib import Path
from pipeline import DB, connect, run_day2

def snapshot(c):
    return {
      'invoice_count':c.execute('SELECT COUNT(*) FROM invoices').fetchone()[0],
      'invoice_state':c.execute("SELECT COALESCE(SUM(amount_usd),0) FROM invoices WHERE status='paid'").fetchone()[0],
      'aug_sep':tuple(tuple(r) for r in c.execute("SELECT invoice_date,COUNT(*),ROUND(SUM(amount_usd),2) FROM invoices WHERE invoice_date>='2026-08-01' AND invoice_date<'2026-10-01' GROUP BY invoice_date ORDER BY invoice_date").fetchall()),
      'history_count':c.execute('SELECT COUNT(*) FROM account_history').fetchone()[0],
    }
c=connect(DB)
before=snapshot(c); run_day2(c,approved=True,load_id='day2-idempotency-check'); after=snapshot(c); c.close()
# sqlite Row tuples are stable by column order; JSON-like output makes the check inspectable.
if before != after:
    print(json.dumps({'idempotent':False,'before':str(before),'after':str(after)},indent=2)); raise SystemExit(1)
print(json.dumps({'idempotent':True,'before':str(before),'after':str(after)},indent=2))
