"""
verify_day2.py — Day-2 delivery verification checklist.

Runs 5 checks and prints PASS/FAIL for each:

  1. 9 JSON files in data/raw/gst/ for 3 base companies
     (COMP_A_RELIANCE, COMP_B_MEDIUM, COMP_C_FRAUD — 3 return types each)
  2. COMP_C_FRAUD ITC gap > 20%  (reconciler)
  3. Circular trading triangle visible in graph (≥ 1 cycle detected)
  4. GNN predicts COMP_C_FRAUD ring with fraud_probability > 0.7
  5. EWS: COMP_C_FRAUD → SMA-2,  COMP_A_RELIANCE → SMA-0
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── project root on path ────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_GST_DIR    = _ROOT / "data" / "raw" / "gst"
_MODEL_PATH = _ROOT / "models" / "gnn_fraud_detector.pt"

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_results: list[tuple[str, bool, str]] = []


def _check(tag: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    print(f"  [{status}] {tag}")
    if detail:
        print(f"         {detail}")
    _results.append((tag, passed, detail))


# ===========================================================================
# Check 1 — 9 JSON files present
# ===========================================================================
print("\n── Check 1: GST JSON files ──────────────────────────────────────────")
BASE_COMPANIES = ["COMP_A_RELIANCE", "COMP_B_MEDIUM", "COMP_C_FRAUD"]
RETURN_TYPES   = ["gstr1", "gstr2a", "gstr3b"]
missing: list[str] = []
found:   list[str] = []

for cid in BASE_COMPANIES:
    for rt in RETURN_TYPES:
        fpath = _GST_DIR / f"{cid}_{rt}.json"
        if fpath.exists():
            found.append(fpath.name)
        else:
            missing.append(fpath.name)

_check(
    "9 GST JSON files present (3 companies × 3 return types)",
    len(missing) == 0,
    f"found={len(found)}, missing={missing}" if missing else f"all {len(found)} files present",
)


# ===========================================================================
# Check 2 — COMP_C_FRAUD ITC gap > 20%
# ===========================================================================
print("\n── Check 2: Reconciler — COMP_C_FRAUD ITC gap ───────────────────────")
try:
    from src.gst.reconciler import GSTReconciler

    rec    = GSTReconciler(gst_dir=str(_GST_DIR))
    report = rec.run_full_reconciliation("COMP_C_FRAUD")

    summary     = report.get("itc_reconciliation", {}).get("summary", {})
    gap_pct     = summary.get("total_gap_percentage", 0.0) or 0.0
    overall     = summary.get("overall_risk", "UNKNOWN")
    fict_count  = (
        report.get("fictitious_vendor_report", {})
              .get("summary", {})
              .get("fictitious_vendor_count", 0) or 0
    )
    _check(
        f"COMP_C_FRAUD ITC gap > 20%  (actual={gap_pct:.1f}%,  risk={overall})",
        abs(gap_pct) > 20.0,
        f"fictitious_vendor_count={fict_count}",
    )
except Exception as exc:
    _check("COMP_C_FRAUD ITC gap > 20%", False, f"ERROR: {exc}")


# ===========================================================================
# Check 3 — Graph circular trading cycle ≥ 1
# ===========================================================================
print("\n── Check 3: Graph — circular trading triangle ───────────────────────")
try:
    from src.gst.graph_builder import TransactionGraphBuilder

    builder = TransactionGraphBuilder(gst_dir=str(_GST_DIR))
    G, risk_scores = builder.run_full_analysis(visualize=False)

    nodes = G.number_of_nodes()
    edges = G.number_of_edges()

    # Count circular-trading cycles logged in edge metadata
    import networkx as nx
    cycles = list(nx.simple_cycles(G))
    cycle_count = len(cycles)

    _check(
        f"Circular cycle detected in graph (cycles={cycle_count})",
        cycle_count >= 1,
        f"graph: {nodes} nodes, {edges} edges",
    )
except Exception as exc:
    _check("Circular cycle detected in graph", False, f"ERROR: {exc}")


# ===========================================================================
# Check 4 — GNN probability > 0.7 for fraud ring nodes
# ===========================================================================
print("\n── Check 4: GNN — COMP_C_FRAUD ring fraud_probability > 0.7 ────────")
try:
    from src.gst.graph_builder import TransactionGraphBuilder  # noqa: F811
    from src.gst.gnn_detector  import CircularTradingDetector, collect_fraud_gstins

    builder2 = TransactionGraphBuilder(gst_dir=str(_GST_DIR))
    G2, _    = builder2.run_full_analysis(visualize=False)

    detector = CircularTradingDetector(
        model_path=_MODEL_PATH if _MODEL_PATH.exists() else None
    )
    if _MODEL_PATH.exists():
        detector.load_model(_MODEL_PATH)
    else:
        fraud_gstins     = collect_fraud_gstins(_GST_DIR)
        data, node_index = detector.convert_to_pyg_data(G2)
        labels           = detector.make_labels(node_index, fraud_gstins)
        detector.train_model(data, labels, epochs=100)

    all_preds = detector.predict_fraud(G2)

    # Collect COMP_C_FRAUD GSTINs from its own files
    import json
    c_fraud_gstins: set[str] = set()
    for rtype in ("gstr1", "gstr2a", "gstr3b"):
        fp = _GST_DIR / f"COMP_C_FRAUD_{rtype}.json"
        if fp.exists():
            data_c = json.loads(fp.read_text())
            if data_c.get("gstin"):
                c_fraud_gstins.add(data_c["gstin"])
            for inv in data_c.get("invoices", []) + data_c.get("auto_populated_invoices", []):
                if inv.get("buyer_gstin"):
                    c_fraud_gstins.add(inv["buyer_gstin"])
                if inv.get("supplier_gstin"):
                    c_fraud_gstins.add(inv["supplier_gstin"])
    c_fraud_gstins.discard("")

    fraud_preds = {g: v for g, v in all_preds.items() if g in c_fraud_gstins}
    high_prob   = {g: v for g, v in fraud_preds.items() if v["fraud_probability"] > 0.7}

    _check(
        f"≥ 1 COMP_C_FRAUD GSTIN with fraud_probability > 0.7",
        len(high_prob) >= 1,
        f"high-risk nodes: {len(high_prob)}/{len(fraud_preds)} "
        + (
            "  top: " + ", ".join(
                f"{g[-6:]}={v['fraud_probability']:.3f}"
                for g, v in sorted(high_prob.items(), key=lambda kv: -kv[1]["fraud_probability"])[:3]
            )
            if high_prob else "(none)"
        ),
    )
except Exception as exc:
    _check("≥ 1 COMP_C_FRAUD GSTIN with fraud_probability > 0.7", False, f"ERROR: {exc}")


# ===========================================================================
# Check 5 — EWS SMA classification
# ===========================================================================
print("\n── Check 5: EWS — SMA classification ───────────────────────────────")
try:
    from src.gst.ews_engine import EWSEngine

    engine = EWSEngine(gst_dir=str(_GST_DIR), model_path=str(_MODEL_PATH))

    fraud_report = engine.consolidate_signals("COMP_C_FRAUD")
    clean_report = engine.consolidate_signals("COMP_A_RELIANCE")

    fraud_sma   = fraud_report["sma_classification"]
    fraud_score = fraud_report["ews_score"]
    clean_sma   = clean_report["sma_classification"]
    clean_score = clean_report["ews_score"]

    _check(
        f"COMP_C_FRAUD  → SMA-2  (score={fraud_score:.3f}, sma={fraud_sma})",
        fraud_sma == "SMA-2",
        "flags: " + ", ".join(
            f"{k.split('_')[0]}={v}" for k, v in fraud_report["flags"].items()
        ),
    )
    _check(
        f"COMP_A_RELIANCE → SMA-0  (score={clean_score:.3f}, sma={clean_sma})",
        clean_sma == "SMA-0",
        "flags: " + ", ".join(
            f"{k.split('_')[0]}={v}" for k, v in clean_report["flags"].items()
        ),
    )
except Exception as exc:
    _check("COMP_C_FRAUD → SMA-2",    False, f"ERROR: {exc}")
    _check("COMP_A_RELIANCE → SMA-0", False, f"ERROR: {exc}")


# ===========================================================================
# Summary
# ===========================================================================
print("\n" + "=" * 70)
total   = len(_results)
passed  = sum(1 for _, ok, _ in _results if ok)
failed  = total - passed
print(f"  RESULTS: {passed}/{total} passed", "✓" if failed == 0 else f"  ({failed} FAILED)")
print("=" * 70 + "\n")

sys.exit(0 if failed == 0 else 1)
