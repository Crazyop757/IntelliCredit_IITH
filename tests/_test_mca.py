"""Unit-tests for MCATool.  Run: python tests/_test_mca.py"""
import importlib.util, pathlib, sys

spec = importlib.util.spec_from_file_location(
    "mca_tool",
    pathlib.Path(__file__).resolve().parents[1] / "src/agent/tools/mca_tool.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

tool = m.MCATool(use_mock_on_block=True)

# ── Test 1: get_company_master — Reliance (via name) ─────────────────────
r = tool.get_company_master("Reliance Industries")
assert r["cin"] == "L17110MH1973PLC019786",        f"Bad CIN: {r['cin']}"
assert r["company_status"] == "Active"
assert r["authorized_capital_inr"] == 150_000_000_000
assert r["paid_up_capital_inr"]    == 67_659_586_735
assert r["last_bs_filing_date"]    == "2023-03-31"
assert r["data_source"] == "mock"
print(f"PASS  Test 1: Reliance master  CIN={r['cin']}  status={r['company_status']}")

# ── Test 2: get_company_master — Tata Motors (via name) ──────────────────
t = tool.get_company_master("Tata Motors")
assert t["cin"] == "L28920MH1945PLC004520",        f"Bad CIN: {t['cin']}"
assert t["registered_address"] is not None
print(f"PASS  Test 2: Tata Motors master  CIN={t['cin']}")

# ── Test 3: get_company_master — CIN lookup ───────────────────────────────
t2 = tool.get_company_master("L28920MH1945PLC004520")
assert t2["cin"] == "L28920MH1945PLC004520"
print(f"PASS  Test 3: CIN lookup  CIN={t2['cin']}")

# ── Test 4: BS overdue flag — generic mock has 2021-03-31 (>2 yrs) ────────
g = tool.get_company_master("Completely Unknown Company XYZ")
assert g["compliance_flags"]["bs_filing_overdue"] is True, "Generic mock BS should be overdue"
print(f"PASS  Test 4: BS overdue flag  date={g['last_bs_filing_date']}")

# ── Test 5: BS NOT overdue for Reliance (2023-03-31 < 2 yrs in context) ───
# Note: today is 2026-03-05, so 2023-03-31 IS ~3 yrs old → overdue
assert r["compliance_flags"]["bs_filing_overdue"] is True
print(f"PASS  Test 5: Reliance BS overdue (2023-03-31 > 2 yrs ago)")

# ── Test 6: get_charges — Reliance ───────────────────────────────────────
cr = tool.get_charges("L17110MH1973PLC019786")
assert cr["total_charges"] == 3
assert cr["open_charges_count"] == 2
assert cr["total_open_charges_amount"] == 800_00_00_000   # ₹800 Cr
assert cr["hidden_debt_flag"] is False                     # declared_debt=None
print(f"PASS  Test 6: Reliance charges  open={cr['open_charges_count']}  "
      f"open_amt=₹{cr['total_open_charges_amount']//1_00_00_000} Cr")

# ── Test 7: get_charges — hidden debt flag ────────────────────────────────
# Declare only ₹100 Cr but open charges are ₹800 Cr → ratio=8x > 1.25 → flag
cr2 = tool.get_charges("L17110MH1973PLC019786", declared_debt_inr=100_00_00_000)
assert cr2["hidden_debt_flag"] is True, "Should flag hidden debt"
assert cr2["hidden_debt_detail"] is not None
print(f"PASS  Test 7: Hidden debt flag triggered  detail={cr2['hidden_debt_detail'][:60]}…")

# ── Test 8: get_charges — satisfied should NOT trigger hidden debt ─────────
cr3 = tool.get_charges("L17110MH1973PLC019786", declared_debt_inr=900_00_00_000)
assert cr3["hidden_debt_flag"] is False, "Open amt ₹800 Cr < declared ₹900 Cr"
print("PASS  Test 8: No hidden debt when declared > open charges")

# ── Test 9: get_director_din — Mukesh Ambani ─────────────────────────────
d = tool.get_director_din("Mukesh Ambani")
assert d["din"] == "00001695",     f"Expected DIN 00001695, got {d['din']}"
assert d["company_count"] == 5
assert d["shell_company_indicator"] is False   # 5 < 10
print(f"PASS  Test 9: Mukesh Ambani  DIN={d['din']}  companies={d['company_count']}")

# ── Test 10: shell company indicator — Chandrasekaran (12 companies) ──────
d2 = tool.get_director_din("Chandrasekaran")
assert d2["shell_company_indicator"] is True,  "12 companies > 10 → shell flag"
assert d2["company_count"] == 12
print(f"PASS  Test 10: Shell flag  director={d2['name']}  companies={d2['company_count']}")

# ── Test 11: _is_cin helper ───────────────────────────────────────────────
assert m._is_cin("L17110MH1973PLC019786") is True
assert m._is_cin("Reliance Industries")   is False
assert m._is_cin("L28920MH1945PLC004520") is True
print("PASS  Test 11: _is_cin helper")

# ── Test 12: _parse_amount helper ────────────────────────────────────────
assert m._parse_amount("5,00,00,000")     == 50_000_000.0    # ₹5 Cr (Indian lakh comma)
assert m._parse_amount("150 Cr")          == 150 * 1_00_00_000
assert m._parse_amount(500_000_000)       == 500_000_000.0
assert m._parse_amount(None)              == 0.0
print("PASS  Test 12: _parse_amount helper")

print()
print("ALL TESTS PASSED (12/12)")
