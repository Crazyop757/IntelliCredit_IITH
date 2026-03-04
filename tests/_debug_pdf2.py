import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pdfplumber
with pdfplumber.open("data/raw/ril_annual_report.pdf") as p:
    print("total pages:", len(p.pages))
    for i in range(min(3, len(p.pages))):
        pg = p.pages[i]
        txt = pg.extract_text() or ""
        print(f"page {i}: {len(txt)} chars, first 150: {repr(txt[:150])}")
