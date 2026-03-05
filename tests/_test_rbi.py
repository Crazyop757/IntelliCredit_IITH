"""Unit-tests for RBIDefaulterTool.  Run: python tests/_test_rbi.py"""
import importlib.util, pathlib

spec = importlib.util.spec_from_file_location(
    "rbi_tool",
    pathlib.Path(__file__).resolve().parents[1] / "src/agent/tools/rbi_tool.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

tool = m.RBIDefaulterTool()
n = tool.load_defaulter_list()
assert n >= 10, f"Expected ≥10 entries, got {n}"
print(f"PASS  Loaded {n} entries")

# ── Test 1: exact match ───────────────────────────────────────────────────
r = tool.check_defaulter("Vijay Mallya")
assert r["is_defaulter"] is True
assert r["match_confidence"] == 1.0
assert r["matched_name"] == "VIJAY MALLYA"
assert r["risk_level"] == "CRITICAL"
print(f"PASS  Test 1: exact match  conf={r['match_confidence']}")

# ── Test 2: case-insensitive ──────────────────────────────────────────────
r2 = tool.check_defaulter("NIRAV MODI")
assert r2["is_defaulter"] is True
assert r2["match_confidence"] == 1.0
print(f"PASS  Test 2: case-insensitive  conf={r2['match_confidence']}")

# ── Test 3: alias match ───────────────────────────────────────────────────
r3 = tool.check_defaulter("Nirav Deepak Modi")
assert r3["is_defaulter"] is True
assert r3["matched_name"] == "NIRAV MODI"
print(f"PASS  Test 3: alias match  matched={r3['matched_name']}")

# ── Test 4: short alias / abbreviation ───────────────────────────────────
r4 = tool.check_defaulter("V. Mallya")
assert r4["is_defaulter"] is True
assert r4["matched_name"] == "VIJAY MALLYA"
print(f"PASS  Test 4: short alias  matched={r4['matched_name']}")

# ── Test 5: fuzzy / misspelling ───────────────────────────────────────────
r5 = tool.check_defaulter("Vijay Malya")   # one missing 'l'
assert r5["is_defaulter"] is True
assert r5["match_confidence"] >= 0.80
print(f"PASS  Test 5: fuzzy/misspelling  conf={r5['match_confidence']:.3f}")

# ── Test 6: company alias ─────────────────────────────────────────────────
r6 = tool.check_defaulter("Kingfisher Airlines Ltd")
assert r6["is_defaulter"] is True
assert "KINGFISHER" in r6["matched_name"]
print(f"PASS  Test 6: company alias  matched={r6['matched_name']}")

# ── Test 7: clean company — no match ──────────────────────────────────────
r7 = tool.check_defaulter("Reliance Industries")
assert r7["is_defaulter"] is False
assert r7["match_confidence"] == 0.0
assert r7["matched_entry"] is None
print("PASS  Test 7: clean company — no match")

# ── Test 8: clean person — no match ───────────────────────────────────────
r8 = tool.check_defaulter("Mukesh Ambani")
assert r8["is_defaulter"] is False
print("PASS  Test 8: clean person — no match")

# ── Test 9: check_company_group — CRITICAL flag ───────────────────────────
g = tool.check_company_group(
    "Kingfisher Airlines Ltd",
    director_names=["Vijay Mallya", "A. Raghunathan"],
)
assert g["is_flagged"] is True
assert g["risk_level"] == "CRITICAL"
assert g["hit_count"] == 2
company_hits = [h for h in g["hits"] if h["screened_as"] == "company"]
director_hits = [h for h in g["hits"] if h["screened_as"] == "director"]
assert len(company_hits) == 1
assert len(director_hits) == 1
print(f"PASS  Test 9: group CRITICAL  hits={g['hit_count']}  summary={g['summary'][:50]}…")

# ── Test 10: check_company_group — CLEAR ─────────────────────────────────
g2 = tool.check_company_group(
    "Reliance Industries",
    director_names=["Mukesh Ambani", "Hital Meswani"],
)
assert g2["is_flagged"] is False
assert g2["risk_level"] == "CLEAR"
assert g2["hit_count"] == 0
print(f"PASS  Test 10: group CLEAR  names_screened={g2['names_screened']}")

# ── Test 11: check_company_group — director alone triggers flag ───────────
g3 = tool.check_company_group(
    "Acme Corp Ltd",                   # unknown company
    director_names=["Mehul Choksi"],   # known defaulter
)
assert g3["is_flagged"] is True
assert g3["hit_count"] == 1
assert g3["hits"][0]["screened_as"] == "director"
print(f"PASS  Test 11: director triggers group flag  hit={g3['hits'][0]['matched_name']}")

# ── Test 12: _normalise helper ────────────────────────────────────────────
assert m._normalise("R.K. Mehta (Ltd)") == "r k mehta limited"
assert m._normalise("") == ""
assert m._normalise("  SBI  ") == "sbi"
print("PASS  Test 12: _normalise helper")

# ── Test 13: load_defaulter_list idempotency ──────────────────────────────
n2 = tool.load_defaulter_list()
assert n2 == n, f"Re-load should return same count {n}, got {n2}"
print(f"PASS  Test 13: re-load idempotency  count={n2}")

# ── Test 14: cutoff enforcement — below-threshold query ──────────────────
r14 = tool.check_defaulter("XYZ Corporation ABC")     # should not match anything
assert r14["is_defaulter"] is False
print("PASS  Test 14: below-threshold — no match")

print()
print("ALL TESTS PASSED (14/14)")
