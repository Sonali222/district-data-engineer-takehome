"""
PR #87 - "Incremental invoice loader + auto schema mapping"
Author: teammate

Description from the PR:
  Loads new billing exports into the warehouse every night. When the vendor changes
  the export format, the LLM mapper figures out the new column names automatically,
  so nobody has to get paged. Ran it twice on my laptop against the v1 file and the
  row counts looked right. Want to schedule it nightly for Meridian starting Friday.
"""

import json
import datetime
import psycopg2
from openai import OpenAI

DB_URL = "postgresql://meridian_admin:Meridian2026!@prod-warehouse.internal:5432/meridian"
client = OpenAI(api_key="sk-proj-9b1e...REDACTED-FOR-HOMEWORK...77cd")

EXPECTED = ["invoice_id", "customer_ref", "amount_cents", "currency", "status", "invoice_date"]
STATE_FILE = "last_run.txt"


def get_watermark():
    try:
        return open(STATE_FILE).read().strip()
    except FileNotFoundError:
        return "1900-01-01"


def set_watermark():
    # Next run only picks up invoices dated after today
    open(STATE_FILE, "w").write(datetime.date.today().isoformat())


def parse_date(s):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%dT00:00:00Z"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass


def llm_map_columns(sample_rows):
    """Ask the model to map whatever fields the vendor sends to our EXPECTED columns."""
    print("Sending sample to LLM:", sample_rows)
    resp = client.chat.completions.create(
        model="gpt-4o",
        temperature=0.7,
        messages=[{
            "role": "user",
            "content": f"Map these fields to {EXPECTED}. Reply with only a JSON dict "
                       f"of new_field -> expected_field.\n{json.dumps(sample_rows)}",
        }],
    )
    return json.loads(resp.choices[0].message.content)


def flatten(rec, mapping):
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[mapping.get(f"{k}.{k2}", k2)] = v2
        else:
            out[mapping.get(k, k)] = v
    return out


def load(path):
    raw = json.load(open(path))
    rows = raw.get("invoices") or raw.get("data")
    mapping = {}
    if set(rows[0].keys()) != set(EXPECTED):
        mapping = llm_map_columns(rows[:20])  # applied straight away

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    watermark = get_watermark()
    loaded = 0

    for r in rows:
        try:
            r = flatten(r, mapping)
            d = parse_date(r["invoice_date"])
            if str(d) <= watermark:
                continue
            amount = float(r["amount_cents"]) / 100
            cur.execute(
                f"INSERT INTO invoices (invoice_id, account_id, amount, currency, status, invoice_date) "
                f"VALUES ('{r['invoice_id']}', '{r['customer_ref']}', {amount}, "
                f"'{r['currency']}', '{r['status']}', '{d}')"
            )
            conn.commit()
            loaded += 1
        except Exception:
            pass

    cur.execute(
        "CREATE TABLE IF NOT EXISTS revenue_by_account AS "
        "SELECT a.account_id, a.segment, SUM(i.amount) AS revenue "
        "FROM invoices i JOIN crm_accounts a ON i.account_id = a.account_id "
        "WHERE i.status = 'paid' GROUP BY 1, 2"
    )
    conn.commit()
    set_watermark()
    print(f"Loaded {loaded} invoices")


if __name__ == "__main__":
    import sys
    load(sys.argv[1])
