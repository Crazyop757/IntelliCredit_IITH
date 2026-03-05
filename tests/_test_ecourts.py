"""Quick unit-tests for ECourtsTool.  Run directly: python tests/_test_ecourts.py"""
import importlib.util, sys, pathlib

# Load module without the package install
spec = importlib.util.spec_from_file_location(
    "ecourts_tool",
    pathlib.Path(__file__).resolve().parents[1] / "src/agent/tools/ecourts_tool.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# ── Test 1: classify_case_severity ────────────────────────────────────────
assert m.ECourtsTool.classify_case_severity("NCLT Insolvency IBC") == "CRITICAL"
assert m.ECourtsTool.classify_case_severity("NI Act S.138 Cheque") == "HIGH"
assert m.ECourtsTool.classify_case_severity("Consumer Forum")      == "LOW"
assert m.ECourtsTool.classify_case_severity("Criminal IPC 420")    == "CRITICAL"
assert m.ECourtsTool.classify_case_severity("Civil Suit")           == "MEDIUM"
print("PASS  Test 1: classify_case_severity")

# ── Test 2: compute_litigation_risk_score NCLT override + score ───────────
cases = [
    {"case_type": "NCLT Insolvency", "severity": "CRITICAL"},
    {"case_type": "NI Act S.138",    "severity": "HIGH"},
    {"case_type": "Consumer Forum",  "severity": "LOW"},
]
score, breakdown, override = m.ECourtsTool.compute_litigation_risk_score(cases)
assert override, "NCLT override must be True"
assert score == 5.5, f"Expected 5.5 got {score}"   # 3.0+2.0+0.5
print(f"PASS  Test 2: score={score}  override={override}  breakdown={breakdown}")

# ── Test 3: cap at 10 ─────────────────────────────────────────────────────
heavy = [{"case_type": "NCLT Insolvency", "severity": "CRITICAL"}] * 5
sc, _, _ = m.ECourtsTool.compute_litigation_risk_score(heavy)
assert sc == 10.0, f"Expected 10.0 got {sc}"
print("PASS  Test 3: score capped at 10.0")

# ── Test 4: mock fallback (live will be blocked in CI) ────────────────────
tool = m.ECourtsTool(use_mock_on_block=True)
report = tool.search_cases("Sample Corp Ltd")
assert report["data_source"] == "mock"
assert report["total_cases"] >= 1
assert "litigation_risk_score" in report
assert "nclt_override" in report
print(f"PASS  Test 4: mock fallback  total_cases={report['total_cases']}  "
      f"score={report['litigation_risk_score']}  nclt_override={report['nclt_override']}")

# ── Test 5: known-clean company stub (0 cases) ────────────────────────────
report2 = tool.search_cases("Tata Steel Limited")
assert report2["total_cases"] == 0, f"Expected 0, got {report2['total_cases']}"
assert report2["litigation_risk_score"] == 0.0
print(f"PASS  Test 5: Tata Steel 0 cases  score={report2['litigation_risk_score']}")

# ── Test 6: date normaliser ───────────────────────────────────────────────
assert m._normalise_date("15-06-2023")  == "2023-06-15"
assert m._normalise_date("15/06/2023")  == "2023-06-15"
assert m._normalise_date("15-Jun-2023") == "2023-06-15"
assert m._normalise_date("2023-06-15")  == "2023-06-15"
assert m._normalise_date(None) is None
print("PASS  Test 6: date normaliser")

print()
print("ALL TESTS PASSED (6/6)")
