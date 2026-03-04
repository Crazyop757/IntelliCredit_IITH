import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pdfplumber

for pdf in ["data/raw/ril_annual_report.pdf", "data/raw/tata_Annual-CSR-Report-2023-24.pdf"]:
    try:
        with pdfplumber.open(pdf) as p:
            n = len(p.pages)
            txt = p.pages[0].extract_text() or "" if n > 0 else ""
            print(f"{pdf}: {n} pages, page0 chars={len(txt)}, text[:80]={repr(txt[:80])}")
    except Exception as e:
        print(f"{pdf}: ERROR — {e}")
