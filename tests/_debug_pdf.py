import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser
p = PDFParser(max_pages=5)
r = p.parse("data/raw/ril_annual_report.pdf")
print("doc_type :", r["doc_type"])
print("pages    :", r["pages_processed"])
print("text 600 :", repr(r["raw_text"][:600]))
print("text 600+:", repr(r["raw_text"][600:1200]))
# keyword check
txt = r["raw_text"].lower()
for kw in ["annual report","board of directors","director","balance sheet","profit","shareholders","dividend"]:
    print(f"  '{kw}' found: {kw in txt}")
