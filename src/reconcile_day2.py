"""Independent source-file calculation for Q6; compares v1 invoice snapshot to v2 overlay."""
import csv,json
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'; OUT=ROOT/'outputs/day2_reconciliation.json'
fx={(r['currency'],r['month']):float(r['usd_per_unit']) for r in csv.DictReader(open(DATA/'v1/fx_rates.csv'))}
fx.update({(r['currency'],r['month']):float(r['usd_per_unit']) for r in csv.DictReader(open(DATA/'day2/fx_rates_2026-10.csv'))})
def date(s):
 for f in ('%Y-%m-%d','%m/%d/%Y','%Y-%m-%dT%H:%M:%SZ'):
  try:return datetime.strptime(s,f).date().isoformat()
  except ValueError: pass
 raise ValueError(s)
def normalize(r):
 d=date(r['invoice_date']); curr=r['currency'].upper(); amt=int(r['amount_cents'])/100
 rate=1 if curr=='USD' else fx.get((curr,d[:7]))
 if rate is None: return {'date':d,'status':r['status'].lower(),'usd':None,'missing_fx':True}
 return {'date':d,'status':r['status'].lower(),'usd':round(amt*rate,2),'missing_fx':False}
old=json.load(open(DATA/'v1/billing_invoices.json'))['invoices']
new=json.load(open(DATA/'day2/billing_invoices_v2.json'))['data']
before={r['invoice_id']:normalize(r) for r in old}
after=dict(before)
for r in new:
 d=date(r['issued_on']); curr=r['amount']['currency'].upper(); amt=float(r['amount']['value']); rate=1 if curr=='USD' else fx.get((curr,d[:7]))
 after[r.get('legacy_id') or r['id']]={'date':d,'status':r['state'].lower(),'usd':None if rate is None else round(amt*rate,2),'missing_fx':rate is None}
result={'method':'Independent aggregation from source exports, not queried from modeled invoice table. FX uses invoice month; per-invoice USD rounded to cents. Missing FX is excluded from the numeric total and disclosed separately.', 'months':{}}
for month in ['2026-08','2026-09']:
 def total(rows):
  eligible=[v for v in rows.values() if v['date'].startswith(month) and v['status']=='paid']
  missing=sum(v['usd'] is None for v in eligible)
  return {'paid_revenue_usd':round(sum(v['usd'] or 0 for v in eligible),2),'paid_invoices_missing_fx':missing,'paid_invoice_count':len(eligible)}
 b=total(before); a=total(after)
 result['months'][month]={'before':b,'after':a,'delta_usd':round(a['paid_revenue_usd']-b['paid_revenue_usd'],2)}
changes=[]
for r in new:
    key=r.get('legacy_id') or r['id']; d=date(r['issued_on']); cur=r['amount']['currency'].upper(); amt=float(r['amount']['value']); rate=1 if cur=='USD' else fx.get((cur,d[:7])); usd=None if rate is None else round(amt*rate,2)
    prior=before.get(key)
    current={'date':d,'status':r['state'].lower(),'usd':usd,'missing_fx':rate is None}
    if prior is None:
        kind='new_paid_invoice' if current['status']=='paid' else 'new_nonpaid_invoice'
        delta=(usd or 0) if current['status']=='paid' else 0
    elif prior['status']=='paid' and current['status']!='paid':
        kind='paid_to_nonpaid_restatement'; delta=-(prior['usd'] or 0)
    elif prior['status']!='paid' and current['status']=='paid':
        kind='nonpaid_to_paid_restatement'; delta=(usd or 0)
    elif prior['status']=='paid' and current['status']=='paid' and prior['usd']!=usd:
        kind='paid_amount_restatement'; delta=(usd or 0)-(prior['usd'] or 0)
    else:
        kind='other_restatement'; delta=0
    changes.append({'invoice_key':key,'month':d[:7],'kind':kind,'prior_status':prior['status'] if prior else None,'new_status':current['status'],'prior_paid_usd':prior['usd'] if prior and prior['status']=='paid' else 0,'new_paid_usd':usd if current['status']=='paid' else 0,'delta_paid_usd':round(delta,2)})
result['change_breakdown']={}
for month in ['2026-08','2026-09']:
    subset=[x for x in changes if x['month']==month]
    grouped={}
    for x in subset:
        g=grouped.setdefault(x['kind'],{'rows':0,'delta_paid_usd':0.0})
        g['rows']+=1; g['delta_paid_usd']=round(g['delta_paid_usd']+x['delta_paid_usd'],2)
    result['change_breakdown'][month]=grouped
result['changed_invoice_details']=[x for x in changes if x['month'] in ('2026-08','2026-09')]
result['v2_rows']={'received':len(new),'rows_with_legacy_id':sum(bool(r.get('legacy_id')) for r in new),'new_invoice_rows':sum(not r.get('legacy_id') for r in new)}
OUT.write_text(json.dumps(result,indent=2)); print(json.dumps(result,indent=2))
