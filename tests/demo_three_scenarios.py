# -*- coding: utf-8 -*-
"""
demo_three_scenarios.py
=======================
End-to-end demo for three representative loan applicants.

  DEMO A — COMP_A_RELIANCE  → Risk Score ~7.5  LOW      → APPROVE (standard terms)
  DEMO B — COMP_B_MEDIUM    → Risk Score ~5.0  MEDIUM   → CONDITIONAL APPROVE
  DEMO C — COMP_C_FRAUD     → Risk Score  0.0  HIGH     → REJECT (circular trading + ITC fraud)

Run from project root:
    python tests/demo_three_scenarios.py
"""

import sys, textwrap, time
sys.path.insert(0, "src")

import pandas as pd
from scorer.credit_scorer import CreditScorer

# ─ helpers ─

LINE = "=" * 70
DLINE = "-" * 70

def _band_label(band: str) -> str:
    return {"PRIME": "[PRIME]", "LOW": "[LOW]", "MEDIUM": "[MEDIUM]", "HIGH": "[HIGH!!]"}  .get(band, "[?]")

def print_section(title: str):
    print(f"\n{LINE}")
    print(f"  {title}")
    print(LINE)

def print_decision(company: str, adj: dict, loan_amount: str, recommendation: str, terms: str):
    band = adj["adjusted_risk_band"]
    score = adj["adjusted_risk_score"]
    label = _band_label(band)
    print(f"\n  {'FINAL CREDIT DECISION':^66}")
    print(DLINE)
    print(f"  Company          : {company}")
    print(f"  Loan Requested   : {loan_amount}")
    print(f"  Model Score      : {adj['model_risk_score_before_adj']:.2f} / 10.00")
    print(f"  Qual. Delta      : {adj['qualitative_delta_applied']:+.2f}")
    print(f"  Adjusted Score   : {score:.2f} / 10.00")
    print(f"  Risk Band        : {label} {band}")
    print(f"  Recommendation   : {recommendation}")
    if terms:
        print(f"  Terms            : {terms}")
    print(DLINE)

def print_shap(shap_dict: dict, label: str):
    all_sv = shap_dict.get("all_shap_values", {})
    if not all_sv:
        return
    print(f"\n  SHAP Explanations -- {label}")
    print(f"  {'Feature':<36}  {'SHAP Value':>10}  Effect")
    print(f"  {'-'*36}  {'-'*10}  {'-'*20}")
    for feat, val in sorted(all_sv.items(), key=lambda x: abs(x[1]), reverse=True)[:6]:
        direction = "^ INCREASES RISK" if val > 0 else "v reduces risk "
        print(f"  {feat:<36}  {val:>+10.4f}  {direction}")

# ─
#  Train the model
# ─

print_section("IntelliCredit — Three-Scenario Demo")
print("  Training LightGBM credit-risk model ...")
t0 = time.time()
cs = CreditScorer()
train_result = cs.train("data/silver/training_data.csv")
print(f"  Model trained in {time.time()-t0:.1f}s  |  Test AUC = {train_result['auc']:.4f}")
print(f"  Samples: {train_result['n_train']} train / {train_result['n_test']} test")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEMO A — COMP_A_RELIANCE  (Strong, investment-grade company)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_section("DEMO A — COMP_A_RELIANCE   (Clean, Strong Company)")
print(textwrap.dedent("""\
  Profile:
    Reliance-like conglomerate.  Strong balance sheet, DSCR > 2.4x,
    minimal litigation, zero wilful-default flags, GST health = 9.77/10.
    No circular trading detected.  Site visit: facility Fair (slight
    deferred maintenance), management mostly transparent, inventory
    slightly below book (supply-chain variance).
"""))

feat_a = {
    "debt_to_equity":              0.38,
    "current_ratio":               1.85,
    "dscr":                        2.40,
    "gst_health_score":            9.77,
    "itc_gap_pct":                -3.89,
    "circular_trading_confidence": 0.02,
    "litigation_count":            0,
    "news_risk_score":             1.2,
    "has_wilful_default_flag":     0,
    "bounce_count":                0,
    # ── New 14 features (LOW RISK profile) ───────────────────────────
    "revenue_growth_yoy":          0.15,   # 15% YoY growth
    "ebitda_margin":               0.22,   # 22% EBITDA margin
    "working_capital_days":        45.0,
    "creditor_days":               35.0,
    "debtor_days":                 30.0,
    "avg_monthly_balance_cr":      25.0,   # INR Cr
    "credit_utilization_pct":      0.45,
    "upi_concentration_pct":       0.20,
    "gst_filing_regularity":       0.95,
    "turnover_consistency_score":  0.92,
    "promoter_pledging_pct":       0.05,
    "sector_npa_rate":             0.03,
    "company_age_years":           45.0,
    "director_count":              10.0,
}

result_a = cs.score(pd.DataFrame([feat_a]))
print(f"  Model Score      : {result_a['risk_score']:.2f} / 10.00  ({result_a['risk_band']})")
print(f"  Default Prob.    : {result_a['default_probability']:.3%}")

# Qualitative: Fair facility, Mostly Transparent mgmt, Slightly Lower inventory
# Breakdown: capacity_util=55 → -1.0  |  Fair facility → -0.5
#            Mostly Transparent → -0.3  |  Slightly Lower inventory → -0.7
# Total: -2.5  (within [-5.0, +2.0] range)
qual_delta_a = -2.5
print(f"\n  Site-visit qualitative breakdown:")
print(f"    Capacity utilisation 55%    :  -1.0  (below 60% threshold)")
print(f"    Facility condition: Fair    :  -0.5")
print(f"    Mgmt transparency: Mostly  :  -0.3")
print(f"    Inventory vs records: Slight:  -0.7")
print(f"    ─")
print(f"    Raw qual delta              :  {qual_delta_a:+.1f}  (clamped to [-5.0, +2.0])")

adj_a = cs.apply_qualitative_adjustment(result_a, qualitative_delta=qual_delta_a)
print_shap(result_a.get("shap_explanations", {}), "COMP_A")
print_decision(
    company="COMP_A_RELIANCE",
    adj=adj_a,
    loan_amount="₹ 50 Cr",
    recommendation="[OK] APPROVE -- Standard Terms",
    terms="12.5% p.a., 60-month term, standard collateral (1.0× cover)",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEMO B — COMP_B_MEDIUM   (Viable but elevated risk)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_section("DEMO B — COMP_B_MEDIUM   (Moderate Risk, Viable)")
print(textwrap.dedent("""\
  Profile:
    Mid-size tier-2 manufacturer.  GST health = 9.63 (Grade A), ITC gap
    clean (-6.17%, within tolerance).  Elevated D/E = 1.75, moderate
    bounce count (2 instances), one pending litigation.  News risk = 3.8
    (some adverse trade-press, no fraud allegations).  Site visit reveals
    evasive management on some topics, low capacity (35%), inventory 
    slightly lower than records, and headcount 20% below stated.
"""))

feat_b = {
    "debt_to_equity":              1.75,
    "current_ratio":               1.18,
    "dscr":                        1.95,
    "gst_health_score":            9.63,
    "itc_gap_pct":                -6.17,
    "circular_trading_confidence": 0.12,
    "litigation_count":            1,
    "news_risk_score":             3.8,
    "has_wilful_default_flag":     0,
    "bounce_count":                2,
    # ── New 14 features (MEDIUM RISK profile) ────────────────────────
    "revenue_growth_yoy":          0.04,   # modest growth
    "ebitda_margin":               0.10,   # thin margin
    "working_capital_days":        95.0,
    "creditor_days":               65.0,
    "debtor_days":                 60.0,
    "avg_monthly_balance_cr":       8.0,
    "credit_utilization_pct":      0.72,
    "upi_concentration_pct":       0.50,
    "gst_filing_regularity":       0.78,
    "turnover_consistency_score":  0.68,
    "promoter_pledging_pct":       0.38,
    "sector_npa_rate":             0.07,
    "company_age_years":           12.0,
    "director_count":               5.0,
}

result_b = cs.score(pd.DataFrame([feat_b]))
print(f"  Model Score      : {result_b['risk_score']:.2f} / 10.00  ({result_b['risk_band']})")
print(f"  Default Prob.    : {result_b['default_probability']:.3%}")

# Qualitative breakdown:
# The quantitative model sees clean books: GST 9.63, ITC at -6.17%, DSCR 1.95.
# However the site-visit uncovered operational & governance gaps NOT captured in
# any model feature:
#   - Operating at just 35% of stated capacity → severe underutilisation   -1.5
#   - Inventory count below records (potential misrepresentation)           -1.0
#   - Headcount 20% below stated (potential fabrication of ops. scale)     -1.0
#   - Evasive management on capex and cash-flow questions                   -1.0
# These are qualitative observations that override the clean quantitative signal.
qual_delta_b = -4.5
print(f"\n  Site-visit qualitative breakdown:")
print(f"    Capacity utilisation 35%    :  -1.5  (severe underutilisation — weak pipeline)")
print(f"    Inventory below records     :  -1.0  (potential misrepresentation — audit flag)")
print(f"    Headcount 20% below stated  :  -1.0  (potential fabrication of ops. scale)")
print(f"    Mgmt transparency: Evasive  :  -1.0  (evasive on capex & cash-flow questions)")
print(f"    ─")
print(f"    Note: Quant model sees clean books — qual delta bridges model gap vs site reality")
print(f"    Raw qual delta              :  {qual_delta_b:+.1f}  → score = {result_b['risk_score']:.2f} {qual_delta_b:+.1f} = {max(0, result_b['risk_score']+qual_delta_b):.2f}")

adj_b = cs.apply_qualitative_adjustment(result_b, qualitative_delta=qual_delta_b)
print_shap(result_b.get("shap_explanations", {}), "COMP_B")
print_decision(
    company="COMP_B_MEDIUM",
    adj=adj_b,
    loan_amount="₹ 20 Cr",
    recommendation="[!!] CONDITIONAL APPROVE -- Enhanced Monitoring",
    terms="14.0% p.a., 48-month term, extra collateral required (1.4× cover), quarterly covenants",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DEMO C — COMP_C_FRAUD    (Fraud — reject)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_section("DEMO C — COMP_C_FRAUD   (High Risk — Fraudulent Activity Detected)")
print(textwrap.dedent("""\
  Profile:
    Multiple red flags: bounced ECS mandates (count=4), adverse press
    (news=7.2/10), and moderate D/E.  BUT IntelliCredit goes further:
    GNN graph analysis detects circular trading at 0.82 confidence across
    a 12-node shadow network.  ITC reconciliation reveals +34.5% over-
    claiming vs GSTR-2A (Rs.4.2 Cr fraudulent input tax credit claimed).
    These GST/GNN signals are the FRAUD-SPECIFIC root cause -- distinct
    from a company that is merely financially stressed.
    EWS flags: gst_itc_fraud_risk=HIGH, circular_trading_risk=HIGH.
    Site visit: 10% capacity, uncooperative management, unverifiable inventory.
"""))

feat_c = {
    "debt_to_equity":              2.80,
    "current_ratio":               1.08,
    "dscr":                        1.82,
    "gst_health_score":            8.80,   # files regularly -- compliance score is misleading
    "itc_gap_pct":                34.5,    # FRAUD: massive ITC over-claim vs GSTR-2A
    "circular_trading_confidence": 0.82,   # FRAUD: circular trading via GNN graph analysis
    "litigation_count":            2,
    "news_risk_score":             7.2,    # adverse press coverage
    "has_wilful_default_flag":     0,
    "bounce_count":                4,      # ECS/cheque bounces
    # ── New 14 features (HIGH RISK / FRAUD profile) ───────────────────
    "revenue_growth_yoy":         -0.15,   # shrinking revenue
    "ebitda_margin":               0.04,   # near-zero margins
    "working_capital_days":       155.0,   # bloated working capital
    "creditor_days":              110.0,
    "debtor_days":                 95.0,
    "avg_monthly_balance_cr":       0.8,   # very thin balance
    "credit_utilization_pct":      0.94,   # nearly maxed out
    "upi_concentration_pct":       0.82,   # suspicious UPI concentration
    "gst_filing_regularity":       0.55,   # irregular GST filing
    "turnover_consistency_score":  0.35,   # inconsistent turnover
    "promoter_pledging_pct":       0.72,   # heavy promoter pledging
    "sector_npa_rate":             0.14,   # high-NPA sector
    "company_age_years":            3.0,   # very young entity
    "director_count":               3.0,   # thin board
}

result_c = cs.score(pd.DataFrame([feat_c]))
print(f"  Model Score      : {result_c['risk_score']:.2f} / 10.00  ({result_c['risk_band']})")
print(f"  Default Prob.    : {result_c['default_probability']:.3%}")

# Qualitative — catastrophic score (but already 0, can't go lower)
# capacity_util=10 → -2.0  |  Poor facility → -1.5  |  Uncooperative mgmt → -3.0
# Raw: -6.5  → capped at -5.0  →  0.0 + (-5.0) = -5.0 → clamped to 0.0
qual_delta_c = -5.0
print(f"\n  Site-visit qualitative breakdown:")
print(f"    Capacity utilisation 10%    :  -2.0")
print(f"    Facility condition: Poor    :  -1.5")
print(f"    Mgmt transparency: Uncoop.  :  -3.0")
print(f"    ─")
print(f"    Raw qual delta              :  -6.5  → capped at -5.0 → score clamped to 0.0")

adj_c = cs.apply_qualitative_adjustment(result_c, qualitative_delta=qual_delta_c)

shap_c = result_c.get("shap_explanations", {})
print_shap(shap_c, "COMP_C — Fraud Signals")

# Highlight the two key fraud signals explicitly
all_sv = shap_c.get("all_shap_values", {})
itc_shap = all_sv.get("itc_gap_pct", 0.0)
ct_shap  = all_sv.get("circular_trading_confidence", 0.0)
print(f"\n  *** FRAUD-SPECIFIC SIGNALS (root cause beyond generic stress): ***")
print(f"    ITC Gap vs GSTR-2A      :  +34.5%   SHAP={itc_shap:+.4f}  -> Over-claimed ITC by Rs.4.2 Cr")
print(f"    Circular Trading Conf.  :  0.82      SHAP={ct_shap:+.4f}  -> 12-node shell network (GNN)")
print(f"    Note: ITC+circular are the FRAUD signals that separate this from a merely stressed company")
print(f"    EWS Risk Flags          :  gst_itc_fraud_risk=HIGH, circular_trading_risk=HIGH")

print_decision(
    company="COMP_C_FRAUD",
    adj=adj_c,
    loan_amount="₹ 15 Cr",
    recommendation="[XX] REJECT -- Fraudulent Activity Detected",
    terms="Refer to SFIO / GST Investigation Wing for ITC fraud inquiry",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SUMMARY TABLE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_section("SUMMARY — Three-Scenario Comparison")
rows = [
    ("COMP_A_RELIANCE", adj_a["model_risk_score_before_adj"], adj_a["qualitative_delta_applied"],
     adj_a["adjusted_risk_score"], adj_a["adjusted_risk_band"], "APPROVE"),
    ("COMP_B_MEDIUM",   adj_b["model_risk_score_before_adj"], adj_b["qualitative_delta_applied"],
     adj_b["adjusted_risk_score"], adj_b["adjusted_risk_band"], "CONDITIONAL"),
    ("COMP_C_FRAUD",    adj_c["model_risk_score_before_adj"], adj_c["qualitative_delta_applied"],
     adj_c["adjusted_risk_score"], adj_c["adjusted_risk_band"], "REJECT"),
]
hdr = f"  {'Company':<22} {'Model':>6} {'Qual':>6} {'Final':>6}  {'Band':<8}  {'Decision'}"
print(hdr)
print("  " + "─" * (len(hdr) - 2))
for company, model_sc, qual_d, final_sc, band, decision in rows:
    label = _band_label(band)
    print(f"  {company:<22} {model_sc:>6.2f} {qual_d:>+6.1f} {final_sc:>6.2f}  "
          f"{label:<9} {decision}")
print()
print("  Risk Scale: PRIME ≥ 8.0  |  LOW 6–8  |  MEDIUM 4–6  |  HIGH < 4")
print()

# Assertions — fail loudly if targets are missed
assert adj_a["adjusted_risk_band"] in ("PRIME", "LOW"), \
    f"COMP_A should be PRIME or LOW, got {adj_a['adjusted_risk_band']}"
assert 6.0 <= adj_a["adjusted_risk_score"] <= 10.0, \
    f"COMP_A score {adj_a['adjusted_risk_score']} out of expected range"

assert adj_b["adjusted_risk_band"] == "MEDIUM", \
    f"COMP_B should be MEDIUM, got {adj_b['adjusted_risk_band']}"
assert 4.0 <= adj_b["adjusted_risk_score"] <= 6.0, \
    f"COMP_B score {adj_b['adjusted_risk_score']} out of expected range"

assert adj_c["adjusted_risk_band"] == "HIGH", \
    f"COMP_C should be HIGH, got {adj_c['adjusted_risk_band']}"
assert adj_c["adjusted_risk_score"] < 4.0, \
    f"COMP_C score {adj_c['adjusted_risk_score']} should be < 4.0"

# SHAP check: itc_gap and circular_trading must both be RISK-INCREASING for COMP_C
# (these are the fraud-specific signals, regardless of rank vs other risk factors)
assert all_sv.get("itc_gap_pct", 0) > 0, \
    f"ITC gap should increase default risk for COMP_C, got SHAP={all_sv.get('itc_gap_pct', 0):.3f}"
assert all_sv.get("circular_trading_confidence", 0) > 0, \
    f"Circular trading should increase default risk for COMP_C, got SHAP={all_sv.get('circular_trading_confidence', 0):.3f}"

print("  [OK] All scenario assertions PASSED")
print()
