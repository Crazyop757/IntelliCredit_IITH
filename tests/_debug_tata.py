import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser, _CLASSIFICATION_KEYWORDS, _MIN_KEYWORD_SCORE

p = PDFParser(max_pages=10)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
print("doc_type :", r["doc_type"])
print("pages    :", r["pages_processed"])
txt = r["raw_text"]
print("text len :", len(txt))
print("text[:300]:", repr(txt[:300]))

if txt:
    low = txt.lower()
    for doc, kws in _CLASSIFICATION_KEYWORDS.items():
        hits = [kw for kw in kws if kw in low]
        print(f"{doc}: {len(hits)} hits — {hits}")
