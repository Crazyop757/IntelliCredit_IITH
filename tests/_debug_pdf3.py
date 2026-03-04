import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# Try pypdf
try:
    from pypdf import PdfReader
    r = PdfReader("data/raw/ril_annual_report.pdf")
    print("pypdf pages:", len(r.pages))
    txt = r.pages[0].extract_text() or ""
    print("page0 chars:", len(txt))
    print("page0 text[:200]:", repr(txt[:200]))
except Exception as e:
    print("pypdf failed:", e)

# Try checking with pdfplumber and catching errors
try:
    import pdfplumber
    with pdfplumber.open("data/raw/ril_annual_report.pdf") as p:
        print("pdfplumber pages:", len(p.pages))
        if len(p.pages) > 0:
            txt = p.pages[0].extract_text() or ""
            print("pdfplumber page0 chars:", len(txt))
except Exception as e:
    print("pdfplumber error:", e)
