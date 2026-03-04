import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pandas as pd
df = pd.read_csv("data/raw/bank_statement_sample.csv", nrows=5)
print("columns:", list(df.columns))
print(df.head())
