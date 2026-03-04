import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.pdf_parser import PDFParser
from src.ingestor.ner_extractor import NERExtractor

p = PDFParser(max_pages=56)
r = p.parse("data/raw/tata_Annual-CSR-Report-2023-24.pdf")
text = r["raw_text"]

e = NERExtractor()
# Try on various slices
for start in [0, 3000, 6000, 10000, 20000]:
    chunk = text[start:start+3000]
    ents = e.extract_entities(chunk)
    persons = ents["PERSON"]
    orgs    = ents["ORG"]
    if persons or orgs:
        print(f"[{start}:{start+3000}] PERSON={persons[:5]}, ORG={orgs[:3]}")
