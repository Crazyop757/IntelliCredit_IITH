import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.financial_extractor import FinancialExtractor
e = FinancialExtractor()
print("methods:", [m for m in dir(e) if not m.startswith("_")])
