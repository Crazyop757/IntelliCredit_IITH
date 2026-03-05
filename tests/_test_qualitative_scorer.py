"""Live end-to-end test of QualitativeScorer including Claude text classification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.scorer.qualitative_scorer import QualitativeScorer

scorer = QualitativeScorer()
result = scorer.compute_adjustment({
    "capacity_utilization":    35,
    "facility_condition":      "Fair",
    "management_transparency": "Evasive on some topics",
    "inventory_vs_records":    "Slightly Lower",
    "employee_count_vs_records": "Matches",
    # Two text fields with clear red-flag content
    "site_visit_observations": (
        "Factory appeared locked. Guards refused entry. No workers on site."
    ),
    "group_company_exposure": (
        "Management mentioned two undisclosed group entities not in submitted documents."
    ),
})

print("total_adjustment :", result["total_adjustment"])
print("severity         :", result["severity"])
print("raw_total        :", result["raw_total"])
print("red_flags_found  :", result["red_flags_found"])
print("summary_text     :", result["summary_text"])
print("breakdown        :")
for k, v in result["breakdown"].items():
    print(f"  {k:<40} {v:+.2f}")

assert result["total_adjustment"] <= -5.0 or result["total_adjustment"] < 0, \
    "Expected negative (risk-raising) adjustment"
assert isinstance(result["red_flags_found"], list)
assert isinstance(result["summary_text"], str) and len(result["summary_text"]) > 10

print("\nALL LIVE TEST ASSERTIONS PASSED.")
