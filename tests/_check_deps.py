import sys
try:
    import pdfplumber
    print("pdfplumber", pdfplumber.__version__)
except ImportError as e:
    print("MISSING:", e)
import difflib
print("difflib OK (stdlib)")
