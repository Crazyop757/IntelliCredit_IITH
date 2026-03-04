import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.bank_analyzer import BankStatementAnalyzer
a = BankStatementAnalyzer()
a.load_transactions("data/raw/bank_statement_sample.csv")
m = a.compute_metrics()
print("txn_count :", m.get("transaction_count"))
print("credits   :", m.get("total_annual_credits"))
print("debits    :", m.get("total_annual_debits"))
print("metrics   :", len(m), "keys")
fl = a.flag_anomalies()
print("anomalies :", len(fl))
