import json, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GOLDEN=json.loads((ROOT/'tests/golden_answers.json').read_text())
sys.path.insert(0,str(ROOT/'src'))
from agent import run_tool

class PipelineTests(unittest.TestCase):
    def test_day1_expected_outputs(self):
        p=ROOT/'outputs/day1_answers.json'
        self.assertTrue(p.exists())
        x=json.loads(p.read_text())
        self.assertEqual(x['Q2_active_customers']['finance'],GOLDEN['day1_finance_active_customers'])
        self.assertEqual(x['Q2_active_customers']['sales'],GOLDEN['day1_sales_active_customers'])
        self.assertAlmostEqual(x['Q3_median_P1_close_hours_2026'],GOLDEN['median_p1_close_hours_2026'],places=2)
    def test_ambiguous_active_asks_clarification(self):
        x=run_tool('How many active customers?',ROOT/'outputs/meridian.db')
        self.assertIn('clarification',x)
        self.assertIn('finance',x['answer']); self.assertIn('sales',x['answer'])
    def test_finance_definition(self):
        x=run_tool('How many finance active customers?',ROOT/'outputs/meridian.db')
        self.assertEqual(x['answer'],GOLDEN['day2_finance_active_customers'] if (ROOT/'outputs/day2_answers.json').exists() else GOLDEN['day1_finance_active_customers'])
        self.assertIn('provenance',x)
    def test_sales_definition(self):
        x=run_tool('How many sales active customers?',ROOT/'outputs/meridian.db')
        self.assertEqual(x['answer'],GOLDEN['day2_sales_active_customers'] if (ROOT/'outputs/day2_answers.json').exists() else GOLDEN['day1_sales_active_customers'])
    def test_p1_median(self):
        x=run_tool('What is the median time to close for P1 tickets in 2026?',ROOT/'outputs/meridian.db')
        self.assertAlmostEqual(x['answer'],20.73,places=2)
    def test_refuses_forecast(self):
        self.assertIsNotNone(run_tool('Forecast next quarter revenue')['refusal'])
    def test_refuses_causal_churn(self):
        self.assertIsNotNone(run_tool('Why did customer leave?')['refusal'])
    def test_paraphrase_active(self):
        x=run_tool('Count the customers finance considers active',ROOT/'outputs/meridian.db')
        self.assertEqual(x['answer'],GOLDEN['day2_finance_active_customers'] if (ROOT/'outputs/day2_answers.json').exists() else GOLDEN['day1_finance_active_customers'])
    def test_paraphrase_p1(self):
        x=run_tool('Give me the median closure duration for P1 tickets opened this year',ROOT/'outputs/meridian.db')
        self.assertAlmostEqual(x['answer'],20.73,places=2)
    def test_day2_question(self):
        x=run_tool('What was paid revenue by segment in October?',ROOT/'outputs/meridian.db')
        self.assertIsInstance(x['answer'],dict)
    def test_restatement_comparison_pushback(self):
        x=run_tool('Compare August and September billing revenue before and after changes',ROOT/'outputs/meridian.db')
        self.assertIsNotNone(x['refusal'])
    def test_q6_independent_reconciliation(self):
        x=json.loads((ROOT/'outputs/day2_reconciliation.json').read_text())
        self.assertAlmostEqual(x['months']['2026-08']['delta_usd'],GOLDEN['q6_august_delta_usd'],places=2)
        self.assertAlmostEqual(x['months']['2026-09']['delta_usd'],GOLDEN['q6_september_delta_usd'],places=2)

if __name__=='__main__': unittest.main()
