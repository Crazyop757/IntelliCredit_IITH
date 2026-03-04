import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser

p = PDFParser(max_pages=20)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
print("doc_type :", r["doc_type"])
print("pages    :", r["pages_processed"])
print("text[:80]:", repr(r["raw_text"][:80]))
