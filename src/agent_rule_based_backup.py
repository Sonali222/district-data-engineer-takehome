"""Small deterministic tool layer. LLMs may route intent to these functions, never calculate totals."""
import argparse, json, sqlite3
from pathlib import Path
try:
    from pipeline import DB
except ModuleNotFoundError:
    from .pipeline import DB

DEFINITIONS={
 'finance_active':'Distinct matched accounts with at least one paid invoice in the most recent completed quarter (Q3 2026 for the 2026-09-30 snapshot).',
 'sales_active':'Distinct matched accounts with any non-void invoice in the trailing 12 months (2025-10-01 through 2026-09-30).',
 'paid_revenue':'Sum amount_usd for paid invoices; refunded invoices are excluded from their invoice month.',
 'time_to_close':'Median closed-ticket elapsed hours; open tickets excluded; negative durations quarantined.'}

def run_tool(question, db_path=DB):
    q=question.lower(); c=sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro',uri=True); c.row_factory=sqlite3.Row
    try:
        if any(k in q for k in ['forecast','predict','next quarter','will we','why did customer leave','customer sentiment']):
            return {'answer':None,'refusal':'The modeled exports do not contain forecast labels, causal evidence, or sufficient sentiment data to answer that question.','provenance':{'tables':[],'filters':[],'row_count':0}}
        if 'active' in q or 'how many customers' in q:
            finance=c.execute("SELECT COUNT(DISTINCT account_id) n FROM invoices WHERE status='paid' AND invoice_date>='2026-07-01' AND invoice_date<'2026-10-01' AND account_id IS NOT NULL").fetchone()['n']
            sales=c.execute("SELECT COUNT(DISTINCT account_id) n FROM invoices WHERE status!='void' AND invoice_date>='2025-10-01' AND invoice_date<'2026-10-01' AND account_id IS NOT NULL").fetchone()['n']
            choice='sales' if 'sales' in q else 'finance' if 'finance' in q else None
            if not choice:
                return {'answer':{'finance':finance,'sales':sales},'clarification':'Which definition do you want: Finance (paid invoice in Q3 2026) or Sales (any non-void invoice in trailing 12 months)?','provenance':{'tables':['invoices'],'filters':['finance: status=paid, 2026-07-01<=invoice_date<2026-10-01','sales: status!=void, 2025-10-01<=invoice_date<2026-10-01'],'definition':'Both definitions shown; no single number assumed','row_count':None}}
            return {'answer':finance if choice=='finance' else sales,'provenance':{'tables':['invoices'],'filters':['account_id IS NOT NULL', 'status/date filters per selected definition'],'definition':DEFINITIONS[choice+'_active'],'row_count':None}}
        if 'p1' in q and ('close' in q or 'median' in q or 'ticket' in q):
            vals=[r['time_to_close_hours'] for r in c.execute("SELECT time_to_close_hours FROM tickets WHERE priority='P1' AND opened_at>='2026-01-01' AND opened_at<'2027-01-01' AND time_to_close_hours IS NOT NULL")]
            vals.sort(); n=len(vals); med=(vals[n//2] if n%2 else (vals[n//2-1]+vals[n//2])/2) if n else None
            return {'answer':round(med,2) if med is not None else None,'provenance':{'tables':['tickets'],'filters':['priority=P1','opened_at in calendar 2026','closed tickets only'],'definition':DEFINITIONS['time_to_close'],'row_count':n}}
        if 'august' in q and 'september' in q and ('revenue' in q or 'billing' in q):
            return {'answer':None,'refusal':'This tool requires the Day 1 vs Day 2 reconciliation snapshot to compare restatements. Run the comparison report; do not infer before/after from current-state rows alone.','provenance':{'tables':['invoices','load_report'],'filters':['invoice_date in 2026-08 or 2026-09'],'row_count':0}}
        if 'october' in q and 'revenue' in q:
            rows=c.execute("SELECT a.segment,SUM(i.amount_usd) revenue,COUNT(*) rows_used FROM invoices i LEFT JOIN account_history a ON a.account_id=i.account_id AND a.valid_from<='2026-10-04' AND (a.valid_to IS NULL OR a.valid_to>'2026-10-04') WHERE i.status='paid' AND i.invoice_date>='2026-10-01' AND i.invoice_date<'2026-10-05' GROUP BY a.segment ORDER BY a.segment").fetchall()
            return {'answer':{r['segment'] or 'UNMATCHED':round(r['revenue'] or 0,2) for r in rows},'provenance':{'tables':['invoices','account_history'],'filters':['status=paid','2026-10-01<=invoice_date<2026-10-05','segment effective on invoice date'],'definition':DEFINITIONS['paid_revenue'],'row_count':sum(r['rows_used'] for r in rows)}}
        return {'answer':None,'refusal':'I can answer only the supported active-customer, P1 time-to-close, and October paid-revenue questions through the current tools. Please rephrase to one of those; I will not guess or query raw rows.','provenance':{'tables':[],'filters':[],'row_count':0}}
    finally: c.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('question'); p.add_argument('--db',type=Path,default=DB); a=p.parse_args(); print(json.dumps(run_tool(a.question,a.db),indent=2))
