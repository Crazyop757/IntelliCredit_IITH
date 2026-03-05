"""Verify the import chain the Streamlit portal uses."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scorer.qualitative_scorer import QualitativeScorer

scorer = QualitativeScorer()
result = scorer.compute_adjustment({"capacity_utilization": 50})
print(f"scorer import OK  total_adjustment={result['total_adjustment']}  severity={result['severity']}")

# Quick round-trip: save to silver dir
import json, uuid
from datetime import datetime, timezone
silver = Path(__file__).resolve().parents[1] / "data" / "silver" / "qualitative_inputs"
silver.mkdir(parents=True, exist_ok=True)
test_file = silver / "_test_write.jsonl"
with test_file.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"id": str(uuid.uuid4()), "total_adjustment": result["total_adjustment"]}) + "\n")
test_file.unlink()   # clean up
print("silver write OK")
print("\nAll portal import/save checks PASSED.")
