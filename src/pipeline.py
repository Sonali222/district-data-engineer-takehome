"""Reproducible Meridian pipeline. Standard-library SQLite keeps the take-home self-contained."""
from __future__ import annotations
import argparse, csv, json, hashlib, re, sqlite3, sys
from collections import Counter
from datetime import datetime, date, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DB = ROOT / 'outputs' / 'meridian.db'
VALID_SEGMENTS = {'SMB','MID-MARKET','ENTERPRISE'}
VALID_STATUS = {'paid','open','void','refunded'}

DDL = '''
CREATE TABLE IF NOT EXISTS raw_rows(load_id TEXT, source_file TEXT, source_row INTEGER, payload TEXT, payload_hash TEXT, loaded_at TEXT, PRIMARY KEY(load_id, source_file, source_row));
CREATE TABLE IF NOT EXISTS quarantine(load_id TEXT, source_file TEXT, source_row INTEGER, reason TEXT, payload TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS load_report(load_id TEXT, source_file TEXT, received INTEGER, loaded INTEGER, updated INTEGER, deduplicated INTEGER, quarantined INTEGER, details TEXT, PRIMARY KEY(load_id, source_file));
CREATE TABLE IF NOT EXISTS account_map(source_account_id TEXT PRIMARY KEY, canonical_account_id TEXT NOT NULL, match_reason TEXT NOT NULL, confidence REAL NOT NULL, approved INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS accounts(account_id TEXT PRIMARY KEY, account_name TEXT, segment TEXT, region TEXT, owner TEXT, created_at TEXT, source_file TEXT, source_row INTEGER);
CREATE TABLE IF NOT EXISTS account_history(account_id TEXT, segment TEXT, region TEXT, owner TEXT, valid_from TEXT, valid_to TEXT, source_file TEXT, source_row INTEGER, PRIMARY KEY(account_id, valid_from));
CREATE TABLE IF NOT EXISTS invoices(invoice_id TEXT PRIMARY KEY, account_id TEXT, amount_native REAL, currency TEXT, status TEXT, invoice_date TEXT, amount_usd REAL, source_file TEXT, source_row INTEGER, updated_at TEXT, raw_customer_ref TEXT);
CREATE TABLE IF NOT EXISTS tickets(ticket_id TEXT PRIMARY KEY, org_name TEXT, account_id TEXT, match_confidence REAL, priority TEXT, opened_at TEXT, closed_at TEXT, csat INTEGER, subject TEXT, time_to_close_hours REAL, source_file TEXT, source_row INTEGER);
CREATE TABLE IF NOT EXISTS fx_rates(currency TEXT, month TEXT, usd_per_unit REAL, source_file TEXT, source_row INTEGER, PRIMARY KEY(currency, month));
CREATE TABLE IF NOT EXISTS metrics(metric_name TEXT PRIMARY KEY, definition TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_invoice_date ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS ix_invoice_account ON invoices(account_id);
CREATE INDEX IF NOT EXISTS ix_ticket_opened ON tickets(opened_at);
'''

def connect(path=DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(path)
    c.row_factory=sqlite3.Row
    c.executescript(DDL)
    return c

def norm_segment(s):
    s=(s or '').strip().upper().replace('_','-')
    return s if s in VALID_SEGMENTS else ('UNKNOWN' if not s else s)

def norm_status(s): return (s or '').strip().lower()
def parse_date(s):
    """ISO first; otherwise explicit US month/day/year (source convention inferred from data)."""
    if s is None or str(s).strip()=='': raise ValueError('missing date')
    s=str(s).strip()
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ','%Y-%m-%dT%H:%M:%SZ','%Y-%m-%d','%m/%d/%Y','%m/%d/%y'):
        try: return datetime.strptime(s,fmt).date().isoformat()
        except ValueError: pass
    raise ValueError(f'unrecognized or ambiguous date format: {s}')

def parse_ts(s):
    if not s: return None
    return datetime.fromisoformat(s.replace('Z','+00:00'))

def record_raw(c, load_id, file, rowno, payload):
    raw=json.dumps(payload,sort_keys=True,default=str)
    c.execute('INSERT OR IGNORE INTO raw_rows VALUES(?,?,?,?,?,?)',(load_id,file,rowno,raw,hashlib.sha256(raw.encode()).hexdigest(),datetime.now(timezone.utc).isoformat()))

def quarantine(c, load_id, file, rowno, reason, payload):
    c.execute('INSERT INTO quarantine VALUES(?,?,?,?,?,?)',(load_id,file,rowno,reason,json.dumps(payload,sort_keys=True,default=str),datetime.now(timezone.utc).isoformat()))

def report(c, load_id, file, received, loaded, updated, dedup, quarantined, details=''):
    c.execute('INSERT OR REPLACE INTO load_report VALUES(?,?,?,?,?,?,?,?)',(load_id,file,received,loaded,updated,dedup,quarantined,details))

def load_fx(c, path, load_id):
    file=str(path.relative_to(ROOT)); rows=list(csv.DictReader(open(path,newline='',encoding='utf-8-sig'))); loaded=0; q=0
    if not rows or set(rows[0]) != {'currency','month','usd_per_unit'}: raise ValueError(f'FX schema mismatch: {file}')
    for i,r in enumerate(rows,2):
        record_raw(c,load_id,file,i,r)
        try:
            rate=float(r['usd_per_unit']); month=r['month']; cur=r['currency'].upper()
            if rate<=0 or not re.fullmatch(r'\d{4}-\d{2}',month): raise ValueError('invalid FX rate/month')
            c.execute('INSERT INTO fx_rates VALUES(?,?,?,?,?) ON CONFLICT(currency,month) DO UPDATE SET usd_per_unit=excluded.usd_per_unit,source_file=excluded.source_file,source_row=excluded.source_row',(cur,month,rate,file,i)); loaded+=1
        except Exception as e: quarantine(c,load_id,file,i,str(e),r); q+=1
    report(c,load_id,file,len(rows),loaded,0,0,q)

def load_crm(c,path,load_id,day2=False):
    file=str(path.relative_to(ROOT)); rows=list(csv.DictReader(open(path,newline='',encoding='utf-8-sig'))); required={'account_id','account_name','segment','region','owner','created_at','last_modified_at'}
    if not rows or set(rows[0]) != required: raise ValueError(f'CRM schema mismatch: {file}: {set(rows[0])}')
    loaded=updated=q=dedup=0; effective='2026-10-01' if day2 else '2025-01-01'
    for i,r in enumerate(rows,2):
        record_raw(c,load_id,file,i,r)
        try:
            aid=r['account_id'].strip(); name=r['account_name'].strip()
            if not aid or not name: raise ValueError('missing account_id/account_name')
            seg=norm_segment(r['segment']); region=(r['region'] or 'UNKNOWN').strip().upper(); owner=(r['owner'] or '').strip() or None
            old=c.execute('SELECT * FROM accounts WHERE account_id=?',(aid,)).fetchone()
            if old:
                if (old['segment'],old['region'],old['owner'],old['account_name']) != (seg,region,owner,name):
                    # Close current history row and open a new effective-dated version.
                    c.execute('UPDATE account_history SET valid_to=? WHERE account_id=? AND valid_to IS NULL',(effective,aid))
                    c.execute('INSERT OR REPLACE INTO account_history VALUES(?,?,?,?,?,?,?,?)',(aid,seg,region,owner,effective,None,file,i))
                    c.execute('UPDATE accounts SET account_name=?,segment=?,region=?,owner=?,source_file=?,source_row=? WHERE account_id=?',(name,seg,region,owner,file,i,aid)); updated+=1
                else: dedup+=1
            else:
                c.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?,?,?)',(aid,name,seg,region,owner,r['created_at'],file,i))
                c.execute('INSERT OR REPLACE INTO account_history VALUES(?,?,?,?,?,?,?,?)',(aid,seg,region,owner,effective,None,file,i)); loaded+=1
            c.execute('INSERT OR REPLACE INTO account_map VALUES(?,?,?,?,1)',(aid,aid,'CRM master account_id',1.0))
        except Exception as e: quarantine(c,load_id,file,i,str(e),r); q+=1
    # Detect duplicate names without auto-merging: mapping candidates are reviewable, merges require evidence.
    dupnames=c.execute('SELECT lower(trim(account_name)) n, group_concat(account_id) ids, count(*) nrows FROM accounts GROUP BY n HAVING count(*)>1').fetchall()
    for d in dupnames:
        ids=[x.strip() for x in d['ids'].split(',')]
        for aid in ids[1:]: c.execute('UPDATE account_map SET match_reason=? , confidence=? , approved=0 WHERE source_account_id=?',('duplicate-name review required',0.75,aid))
    report(c,load_id,file,len(rows),loaded,updated,dedup,q,f'duplicate_name_groups={len(dupnames)}')

def canonical_ref(ref):
    s=str(ref).strip()
    if s.isdigit(): return f'ACC-{int(s):05d}'
    if re.fullmatch(r'C\d+',s,re.I): return f'ACC-{int(s[1:]):05d}'
    if re.fullmatch(r'ACC-\d+',s,re.I): return 'ACC-'+s.split('-')[1].zfill(5)
    return None

def amount_usd(c, amount, currency, day):
    month=day[:7]
    if currency=='USD': rate=1.0
    else:
        r=c.execute('SELECT usd_per_unit FROM fx_rates WHERE currency=? AND month=?',(currency,month)).fetchone()
        if not r: raise ValueError(f'missing FX rate {currency}/{month}')
        rate=float(r[0])
    return round(amount*rate,2)

def load_billing_v1(c,path,load_id):
    file=str(path.relative_to(ROOT)); payload=json.load(open(path)); rows=payload.get('invoices')
    if not isinstance(rows,list) or not rows: raise ValueError('billing v1 schema mismatch: expected invoices list')
    required={'invoice_id','customer_ref','amount_cents','currency','status','invoice_date'}
    loaded=updated=q=dedup=0; seen=set()
    for i,r in enumerate(rows,1):
        record_raw(c,load_id,file,i,r)
        try:
            if set(r)!=required: raise ValueError('billing v1 row schema mismatch')
            iid=str(r['invoice_id']).strip()
            if iid in seen: dedup+=1; continue
            day=parse_date(r['invoice_date']); cur=r['currency'].upper(); status=norm_status(r['status'])
            if status not in VALID_STATUS: raise ValueError(f'invalid status {status}')
            cents=int(r['amount_cents']); amount=cents/100
            aid=canonical_ref(r['customer_ref']); matched=bool(aid and c.execute('SELECT 1 FROM accounts WHERE account_id=?',(aid,)).fetchone())
            account=aid if matched else None
            usd=amount_usd(c,amount,cur,day)
            old=c.execute('SELECT * FROM invoices WHERE invoice_id=?',(iid,)).fetchone()
            vals=(account,amount,cur,status,day,usd,file,i,None,str(r['customer_ref']))
            if old:
                c.execute('UPDATE invoices SET account_id=?,amount_native=?,currency=?,status=?,invoice_date=?,amount_usd=?,source_file=?,source_row=?,updated_at=?,raw_customer_ref=? WHERE invoice_id=?',(*vals,iid)); updated+=1
            else:
                c.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,*vals)); loaded+=1
            seen.add(iid)
        except Exception as e: quarantine(c,load_id,file,i,str(e),r); q+=1
    report(c,load_id,file,len(rows),loaded,updated,dedup,q)

def load_billing_v2(c,path,load_id,approved=False):
    file=str(path.relative_to(ROOT)); payload=json.load(open(path)); rows=payload.get('data')
    if not isinstance(rows,list) or not rows: raise ValueError('billing v2 schema mismatch: expected data list')
    expected={'id','legacy_id','account','amount','state','issued_on','updated_at'}
    if set(rows[0]) != expected or not isinstance(rows[0].get('account'),dict) or not isinstance(rows[0].get('amount'),dict): raise ValueError('unrecognized billing v2 schema; no rows loaded')
    if not approved: raise PermissionError('Detected billing schema v2. Review docs/schema_v2_mapping.md and rerun with --approve-schema-v2')
    loaded=updated=q=dedup=0; seen=set()
    for i,r in enumerate(rows,1):
        record_raw(c,load_id,file,i,r)
        try:
            if set(r)!=expected: raise ValueError('billing v2 row schema mismatch')
            iid=(r.get('legacy_id') or '').strip() or str(r['id']).strip()
            if iid in seen: dedup+=1; continue
            day=parse_date(r['issued_on']); cur=r['amount']['currency'].upper(); amount=float(r['amount']['value']); status=norm_status(r['state'])
            if status not in VALID_STATUS: raise ValueError(f'invalid status {status}')
            ref=(r.get('account') or {}).get('id'); aid=canonical_ref(ref); matched=bool(aid and c.execute('SELECT 1 FROM accounts WHERE account_id=?',(aid,)).fetchone())
            usd=amount_usd(c,amount,cur,day)
            old=c.execute('SELECT * FROM invoices WHERE invoice_id=?',(iid,)).fetchone()
            vals=(aid if matched else None,amount,cur,status,day,usd,file,i,r.get('updated_at'),str(ref))
            if old:
                # Avoid older or repeated snapshots overwriting a newer restatement.
                incoming=r.get('updated_at') or ''
                if incoming >= (old['updated_at'] or ''):
                    c.execute('UPDATE invoices SET account_id=?,amount_native=?,currency=?,status=?,invoice_date=?,amount_usd=?,source_file=?,source_row=?,updated_at=?,raw_customer_ref=? WHERE invoice_id=?',(*vals,iid)); updated+=1
                else: dedup+=1
            else:
                c.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?,?,?,?)',(iid,*vals)); loaded+=1
            seen.add(iid)
        except Exception as e: quarantine(c,load_id,file,i,str(e),r); q+=1
    report(c,load_id,file,len(rows),loaded,updated,dedup,q,'schema v2 approved; legacy_id used for restatements; id used for new invoices')

def ticket_match(org, accounts):
    def clean(s): return re.sub(r'[^a-z0-9]+',' ',(s or '').lower()).strip()
    n=clean(org); best=None; score=0
    for a in accounts:
        an=clean(a['account_name'])
        s=SequenceMatcher(None,n,an).ratio()
        # containment handles legal suffixes and minor punctuation variations
        if n and an and (n in an or an in n): s=max(s,0.88)
        if s>score: best,score=a,s
    if best and score>=0.90: return best['account_id'],round(score,3)
    return None,round(score,3)

def load_tickets(c,path,load_id):
    file=str(path.relative_to(ROOT)); rows=[]; q=loaded=updated=dedup=0
    with open(path,encoding='utf-8') as f:
        for line in f:
            if line.strip(): rows.append(json.loads(line))
    accounts=[dict(x) for x in c.execute('SELECT account_id,account_name FROM accounts')]
    for i,r in enumerate(rows,1):
        record_raw(c,load_id,file,i,r)
        try:
            required={'ticket_id','org_name','priority','opened_at','closed_at','csat','subject'}
            if set(r)!=required: raise ValueError('ticket row schema mismatch')
            opened=parse_ts(r['opened_at']); closed=parse_ts(r['closed_at']) if r.get('closed_at') else None
            if opened is None: raise ValueError('missing opened_at')
            closehours=None
            if closed:
                closehours=(closed-opened).total_seconds()/3600
                if closehours<0: raise ValueError('closed_at before opened_at')
            priority=(r['priority'] or '').strip().upper()
            priority={'SEV1':'P1','SEV2':'P2','SEV3':'P3','SEV4':'P4'}.get(priority,priority)
            if priority not in {'P1','P2','P3','P4'}: raise ValueError(f'invalid priority {priority}')
            aid,conf=ticket_match(r['org_name'],accounts)
            old=c.execute('SELECT 1 FROM tickets WHERE ticket_id=?',(r['ticket_id'],)).fetchone()
            vals=(r['org_name'],aid,conf,priority,r['opened_at'],r.get('closed_at'),r.get('csat'),r.get('subject'),closehours,file,i)
            if old: dedup+=1; continue
            c.execute('INSERT INTO tickets VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(r['ticket_id'],*vals)); loaded+=1
        except Exception as e: quarantine(c,load_id,file,i,str(e),r); q+=1
    report(c,load_id,file,len(rows),loaded,updated,dedup,q)

def setup_metrics(c):
    defs={
      'paid_revenue':'Sum amount_usd for status=paid; refunded invoices excluded in their invoice month.',
      'active_finance':'Distinct matched accounts with >=1 paid invoice in the most recent completed quarter.',
      'active_sales':'Distinct matched accounts with any non-void invoice in trailing 12 months.',
      'churn':'Accounts with a paid invoice in prior 12 months and no paid/open invoice since the churn cutoff; disclose exact window.',
      'time_to_close':'Median non-negative (closed_at-opened_at) hours for closed tickets matching priority and period.'}
    c.executemany('INSERT OR REPLACE INTO metrics VALUES(?,?)',defs.items())

def run_day1(c):
    c.execute('BEGIN')
    load_id='day1-v1'
    load_crm(c,DATA/'v1/crm_accounts.csv',load_id)
    load_fx(c,DATA/'v1/fx_rates.csv',load_id)
    load_billing_v1(c,DATA/'v1/billing_invoices.json',load_id)
    load_tickets(c,DATA/'v1/support_tickets.jsonl',load_id)
    setup_metrics(c); c.commit()

def run_day2(c,approved=False,load_id='day2-2026-10-05'):
    c.execute('BEGIN')
    load_crm(c,DATA/'day2/crm_accounts_2026-10-05.csv',load_id,day2=True)
    load_fx(c,DATA/'day2/fx_rates_2026-10.csv',load_id)
    load_billing_v2(c,DATA/'day2/billing_invoices_v2.json',load_id,approved=approved)
    c.commit()

def median(xs):
    xs=sorted(xs); n=len(xs)
    return None if not n else (xs[n//2] if n%2 else (xs[n//2-1]+xs[n//2])/2)

def answers(c,day2=False):
    # Q1 uses segment effective at each invoice date, not current segment.
    def segment_for(aid,day):
        r=c.execute('SELECT segment FROM account_history WHERE account_id=? AND valid_from<=? AND (valid_to IS NULL OR valid_to>?) ORDER BY valid_from DESC LIMIT 1',(aid,day,day)).fetchone()
        return r['segment'] if r else 'UNMATCHED'
    def revenue_by_segment(start,end):
        rows=c.execute("SELECT account_id,invoice_date,amount_usd FROM invoices WHERE status='paid' AND invoice_date>=? AND invoice_date<?",(start,end)).fetchall()
        totals=Counter()
        for r in rows: totals[segment_for(r['account_id'],r['invoice_date']) if r['account_id'] else 'UNMATCHED']+=r['amount_usd'] or 0
        return {k:round(v,2) for k,v in sorted(totals.items())}
    q1={'Q2 2026':revenue_by_segment('2026-04-01','2026-07-01'),'Q2 2025':revenue_by_segment('2025-04-01','2025-07-01')}
    finance=c.execute("SELECT COUNT(DISTINCT account_id) FROM invoices WHERE status='paid' AND invoice_date>='2026-07-01' AND invoice_date<'2026-10-01' AND account_id IS NOT NULL").fetchone()[0]
    sales=c.execute("SELECT COUNT(DISTINCT account_id) FROM invoices WHERE status!='void' AND invoice_date>='2025-10-01' AND invoice_date<'2026-10-01' AND account_id IS NOT NULL").fetchone()[0]
    q3=median([r[0] for r in c.execute("SELECT time_to_close_hours FROM tickets WHERE priority='P1' AND opened_at>='2026-01-01' AND opened_at<'2027-01-01' AND time_to_close_hours IS NOT NULL")])
    top=c.execute("SELECT i.account_id,a.account_name,SUM(i.amount_usd) rev,COUNT(DISTINCT t.ticket_id) tickets FROM invoices i LEFT JOIN accounts a ON a.account_id=i.account_id LEFT JOIN tickets t ON t.account_id=i.account_id AND t.opened_at>='2025-10-01' AND t.opened_at<'2026-10-01' WHERE i.status='paid' AND i.invoice_date>='2025-10-01' AND i.invoice_date<'2026-10-01' AND i.account_id IS NOT NULL GROUP BY i.account_id,a.account_name ORDER BY rev DESC LIMIT 10").fetchall()
    # Avoid invoice x ticket fanout by separate ticket count in final top list.
    top=[]
    for r in c.execute("SELECT i.account_id,a.account_name,SUM(i.amount_usd) rev FROM invoices i LEFT JOIN accounts a ON a.account_id=i.account_id WHERE i.status='paid' AND i.invoice_date>='2025-10-01' AND i.invoice_date<'2026-10-01' AND i.account_id IS NOT NULL GROUP BY i.account_id,a.account_name ORDER BY rev DESC LIMIT 10"):
        tc=c.execute("SELECT COUNT(*) FROM tickets WHERE account_id=? AND opened_at>='2025-10-01' AND opened_at<'2026-10-01'",(r['account_id'],)).fetchone()[0]
        top.append({'account_id':r['account_id'],'account_name':r['account_name'],'paid_revenue_usd':round(r['rev'],2),'tickets':tc})
    q5=c.execute("SELECT COUNT(DISTINCT a.account_id) FROM invoices a WHERE a.invoice_date>='2025-01-01' AND a.invoice_date<'2025-07-01' AND a.account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM invoices b WHERE b.account_id=a.account_id AND b.status IN ('paid','open') AND b.invoice_date>='2026-04-01')").fetchone()[0]
    q6={}
    # Day2 Q6 uses updated invoice rows and report records previous value unavailable unless we snapshot before Day2.
    if day2:
        q6={'note':'Run before Day 2 snapshot is required for auditable before/after values; use outputs/day1_answers.json produced by `answers` command.'}
        octrev=revenue_by_segment('2026-10-01','2026-10-05')
    else: octrev={}
    return {'Q1_paid_revenue_by_segment_usd':q1,'Q2_active_customers':{'finance':finance,'sales':sales},'Q3_median_P1_close_hours_2026':round(q3,2) if q3 is not None else None,'Q4_top10_trailing12m':top,'Q5_H1_2025_billed_no_paid_or_open_since_2026_04_01':q5,'Q7_oct1_4_paid_revenue_by_segment_usd':octrev}

def save_answers(c,day2=False):
    out=answers(c,day2)
    target=ROOT/'outputs'/('day2_answers.json' if day2 else 'day1_answers.json')
    target.write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

def main():
    global DB
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['day1','day2','answers','tests','report']); p.add_argument('--approve-schema-v2',action='store_true'); p.add_argument('--db',type=Path,default=DB); args=p.parse_args()
    DB=args.db
    c=connect(DB)
    try:
        if args.command=='day1': run_day1(c); save_answers(c,False)
        elif args.command=='day2': run_day2(c,args.approve_schema_v2); save_answers(c,True)
        elif args.command=='answers': save_answers(c, c.execute("SELECT 1 FROM load_report WHERE load_id='day2-2026-10-05'").fetchone() is not None)
        elif args.command=='report': print(json.dumps([dict(r) for r in c.execute('SELECT * FROM load_report ORDER BY load_id,source_file')],indent=2))
        elif args.command=='tests':
            checks={
             'unique_invoice_ids':c.execute('SELECT COUNT(*)=COUNT(DISTINCT invoice_id) FROM invoices').fetchone()[0],
             'no_invalid_status':c.execute("SELECT COUNT(*)=0 FROM invoices WHERE status NOT IN ('paid','open','void','refunded')").fetchone()[0],
             'positive_fx':c.execute('SELECT COUNT(*)=0 FROM fx_rates WHERE usd_per_unit<=0').fetchone()[0],
             'valid_ticket_priority':c.execute("SELECT COUNT(*)=0 FROM tickets WHERE priority NOT IN ('P1','P2','P3','P4')").fetchone()[0],
             'nonnegative_close_time':c.execute('SELECT COUNT(*)=0 FROM tickets WHERE time_to_close_hours<0').fetchone()[0],
             'invoice_join_coverage_at_least_95pct':(lambda x: x[0] == 0 or x[1]/x[0] >= 0.95)(c.execute('SELECT COUNT(*),SUM(account_id IS NOT NULL) FROM invoices').fetchone()),
             'ticket_join_coverage_at_least_75pct':(lambda x: x[0] == 0 or x[1]/x[0] >= 0.75)(c.execute('SELECT COUNT(*),SUM(account_id IS NOT NULL) FROM tickets').fetchone()),
            }
            print(json.dumps({'checks':checks,'passed':sum(bool(v) for v in checks.values()),'total':len(checks),'invoice_join_coverage':c.execute('SELECT ROUND(100.0*SUM(account_id IS NOT NULL)/COUNT(*),2) FROM invoices').fetchone()[0],'ticket_join_coverage':c.execute('SELECT ROUND(100.0*SUM(account_id IS NOT NULL)/COUNT(*),2) FROM tickets').fetchone()[0]},indent=2))
            if not all(checks.values()): sys.exit(1)
    finally: c.close()
if __name__=='__main__': main()
