import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.ingestor.ner_extractor import NERExtractor
e = NERExtractor()
# check what public methods exist
print("methods:", [m for m in dir(e) if not m.startswith("_")])
result = e.analyze("Board of Directors Mukesh D. Ambani Chairman Nita M. Ambani Director Nikhil R. Meswani Director")
print("result keys:", list(result.keys()))
import json
print(json.dumps(result, indent=2, default=str))
