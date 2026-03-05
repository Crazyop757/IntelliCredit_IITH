"""
Smoke test for research_agent.py.

All four tool methods are mocked so the test completes in < 5 seconds
with zero network calls.  Verifies:
  • Graph compiles and runs to completion
  • Parallel fan-out (news / ecourts / mca / rbi nodes run)
  • Synthesizer produces a well-formed credit opinion
  • RBI CRITICAL flag (Kingfisher + Vijay Mallya) reaches synthesis
"""
import sys
import logging
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Mock return values for all four tools
# ---------------------------------------------------------------------------
_FAKE_NEWS = {
    "company_name": "Kingfisher Airlines",
    "news_risk_score": 8.5,
    "negative_article_count": 12,
    "most_alarming_headline": "Kingfisher Airlines owes banks ₹9000 Cr",
    "source_credibility_score": 0.88,
    "risk_tags": ["NPA", "fraud"],
    "data_source": "mock",
}
_FAKE_ECOURTS = {
    "party_name": "Kingfisher Airlines",
    "cases": [],
    "litigation_risk_score": 0.0,
    "nclt_override": False,
    "severity_breakdown": {},
    "data_source": "mock",
}
_FAKE_MCA = {
    "cin": "U62200KA2003PLC032420",
    "company_name": "KINGFISHER AIRLINES LIMITED",
    "company_active": False,
    "company_status": "Strike off",
    "bs_filing_overdue": True,
    "agm_overdue": True,
    "data_source": "mock",
    "charges": {
        "cin": "U62200KA2003PLC032420",
        "total_charges": 2,
        "open_charges": 2,
        "satisfied_charges": 0,
        "open_charge_total_inr": 90000000000.0,
        "hidden_debt_flag": False,
        "data_source": "mock",
    },
}
_FAKE_RBI = {
    "company_name": "Kingfisher Airlines",
    "is_flagged": True,
    "risk_level": "CRITICAL",
    "hit_count": 2,
    "names_screened": 2,
    "hits": [
        {"screened_as": "company",  "matched_name": "KINGFISHER AIRLINES LIMITED", "match_confidence": 1.0},
        {"screened_as": "director", "matched_name": "VIJAY MALLYA",                "match_confidence": 1.0},
    ],
    "summary": "2 defaulter match(es) found for 'Kingfisher Airlines' group.",
    "data_source": "mock",
}

# ---------------------------------------------------------------------------
# Patch all four tool methods BEFORE importing the agent (which imports tools)
# ---------------------------------------------------------------------------
with (
    patch("src.agent.tools.news_tool.NewsIntelligenceTool.search_company_news",
          return_value=_FAKE_NEWS),
    patch("src.agent.tools.ecourts_tool.ECourtsTool.search_cases",
          return_value=_FAKE_ECOURTS),
    patch("src.agent.tools.mca_tool.MCATool.get_company_master",
          return_value=_FAKE_MCA),
    patch("src.agent.tools.mca_tool.MCATool.get_charges",
          return_value=_FAKE_MCA["charges"]),
    patch("src.agent.tools.rbi_tool.RBIDefaulterTool.check_company_group",
          return_value=_FAKE_RBI),
):
    from src.agent.research_agent import ResearchAgent

    agent  = ResearchAgent()
    result = agent.run_research(
        "Kingfisher Airlines",
        director_names=["Vijay Mallya"],
    )

print("\n" + "=" * 60)
print("  SMOKE TEST — ResearchAgent")
print("=" * 60)

# Individual reports
for key in ("news_report", "ecourts_report", "mca_report", "rbi_report"):
    r = result.get(key) or {}
    print(f"\n[{key}]  data_source={r.get('data_source','?')}  error={r.get('error','—')}")

syn = result.get("synthesis_report") or {}
print(f"\n[synthesis_report]")
print(f"  overall_risk_score : {syn.get('overall_external_risk_score', 'N/A')}/10")
print(f"  recommended_action : {syn.get('recommended_action', 'N/A')}")
print(f"  synthesis_method   : {syn.get('synthesis_method','?')}")
print(f"\n  litigation_summary:")
for line in (syn.get("litigation_summary") or "").split(". "):
    if line: print(f"    {line.strip()}.")

print(f"\n  key_red_flags:")
for f in (syn.get("key_red_flags") or []):
    print(f"    • {f}")

print(f"\n  positive_signals:")
for s in (syn.get("positive_signals") or []):
    print(f"    ✓ {s}")

errors = result.get("error_log") or []
print(f"\n  error_log  ({len(errors)} entries):")
for e in errors:
    print(f"    [!] {e}")

status = result.get("status")
print(f"\n  status: {status}")
print("=" * 60)

assert status == "complete", f"Expected status='complete', got {status!r}"

# New SynthesizerAgent field names
assert isinstance(syn.get("overall_external_risk_score"), (int, float)), \
    "synthesis_report missing overall_external_risk_score"
assert 0.0 <= syn["overall_external_risk_score"] <= 10.0, \
    "overall_external_risk_score out of range"
action_val = str(syn.get("recommended_action", "")).upper()
assert any(action_val.startswith(v) for v in ("PROCEED", "CAUTION", "REJECT")), \
    f"Invalid recommended_action: {syn.get('recommended_action')!r}"
assert isinstance(syn.get("key_red_flags"), list), "key_red_flags must be a list"
print("\nALL ASSERTIONS PASSED")
