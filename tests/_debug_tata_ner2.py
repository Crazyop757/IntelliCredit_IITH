import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser
from src.ingestor.ner_extractor import NERExtractor
import logging
logging.disable(logging.CRITICAL)

p = PDFParser(max_pages=56)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
text = r["raw_text"]

e = NERExtractor()
# Search through text in 3000-char windows
found = []
for start in range(0, min(len(text), 60000), 2000):
    chunk = text[start:start+3000]
    ents = e.extract_entities(chunk)
    persons = ents["PERSON"]
    orgs    = ents["ORG"]
    if persons:
        found.append(f"[{start}:{start+3000}] PERSON={persons[:6]}, ORG={orgs[:3]}")

if found:
    for f in found[:5]:
        print(f)
else:
    print("No PERSON entities found in first 60k chars")

# Show total full-text entity count
all_ents = e.extract_entities(text[:30000])
print(f"\nFull 30k chars: PERSON={all_ents['PERSON'][:8]}, ORG={all_ents['ORG'][:5]}")
