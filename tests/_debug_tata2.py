import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser
from src.ingestor.financial_extractor import FinancialExtractor

p = PDFParser(max_pages=20)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
text = r["raw_text"]

# Show text samples to understand what figures and directors look like
print("=== text[0:1000] ===")
print(text[:1000])
print("\n=== text[5000:6000] ===")
print(text[5000:6000])
print("\n=== text[10000:11000] ===")
print(text[10000:11000])

# Search for crore / lakh / rupee / Rs patterns
import re
money_hits = re.findall(r'.{0,40}(?:crore|lakh|rupee|rs\.?|₹|\binr\b|\brs\b).{0,40}', text.lower())
print(f"\n=== INR mentions ({len(money_hits)}) ===")
for h in money_hits[:15]:
    print(" ", repr(h))

# Search for person names / directors
dir_hits = re.findall(r'.{0,50}(?:director|chairm|ceo|managing|trustee|mr\.|ms\.|mrs\.|dr\.).{0,50}', text.lower())
print(f"\n=== Director/person mentions ({len(dir_hits)}) ===")
for h in dir_hits[:10]:
    print(" ", repr(h))
