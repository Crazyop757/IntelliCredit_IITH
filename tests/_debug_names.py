import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser
import logging
logging.disable(logging.CRITICAL)

p = PDFParser(max_pages=56)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
text = r["raw_text"]

# Find lines with Dr. / Mr. / Ms. / named person mentions
lines_with_names = []
for line in text.splitlines():
    if re.search(r'\b(Mr|Ms|Mrs|Dr|Shri|Smt)[\.\s]+[A-Z]', line):
        lines_with_names.append(line.strip())

print(f"Lines with title+name: {len(lines_with_names)}")
for ln in lines_with_names[:20]:
    print(" ", repr(ln[:120]))
