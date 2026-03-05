"""
train_gnn.py — Training script for the GNN fraud detector.

Run from project root via WSL:
    python tests/train_gnn.py
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is on the path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.gst.data_generator import GSTDataGenerator
from src.gst.graph_builder import TransactionGraphBuilder
from src.gst.gnn_detector import CircularTradingDetector, collect_fraud_gstins, GST_RAW_DIR

# ---------------------------------------------------------------------------
# Step 1: Generate synthetic data (2 clean + 3 fraud companies)
# ---------------------------------------------------------------------------
print("=" * 60)
print("Step 1: Generating synthetic GST data …")
print("=" * 60)

gen = GSTDataGenerator()
companies_clean = ["COMP_A_RELIANCE", "COMP_B_MEDIUM"]
companies_fraud = ["COMP_C_FRAUD", "COMP_D_FRAUD2", "COMP_E_FRAUD3"]

for name in companies_clean:
    if not os.path.exists(GST_RAW_DIR / f"{name}_gstr1.json"):
        print(f"  Generating {name} (clean) …")
        gen.generate_company_data(name, inject_fraud=False)
    else:
        print(f"  {name} already exists — skipping.")

for name in companies_fraud:
    if not os.path.exists(GST_RAW_DIR / f"{name}_gstr1.json"):
        print(f"  Generating {name} (fraud) …")
        gen.generate_company_data(name, inject_fraud=True)
    else:
        print(f"  {name} already exists — skipping.")

# ---------------------------------------------------------------------------
# Step 2: Build transaction graph
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 2: Building transaction graph …")
print("=" * 60)

builder = TransactionGraphBuilder()
all_data: dict = {}

for company in companies_clean + companies_fraud:
    all_data[company] = {
        "gstr1":  json.load(open(GST_RAW_DIR / f"{company}_gstr1.json")),
        "gstr2a": json.load(open(GST_RAW_DIR / f"{company}_gstr2a.json")),
        "gstr3b": json.load(open(GST_RAW_DIR / f"{company}_gstr3b.json")),
    }

graph = builder.build_graph(list(all_data.values()))
print(f"  Graph built: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

# ---------------------------------------------------------------------------
# Step 3: Collect fraud labels
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 3: Collecting fraud labels …")
print("=" * 60)

fraud_gstins = collect_fraud_gstins(GST_RAW_DIR)
print(f"  Known fraud GSTINs: {len(fraud_gstins)}")
for g in sorted(fraud_gstins):
    print(f"    {g}")

# ---------------------------------------------------------------------------
# Step 4: Convert graph to PyG format + build labels
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 4: Converting to PyG format …")
print("=" * 60)

detector = CircularTradingDetector()
data, node_index = detector.convert_to_pyg_data(graph)
print(f"  x:          {data.x.shape}")
print(f"  edge_index: {data.edge_index.shape}")
print(f"  edge_attr:  {data.edge_attr.shape}")

labels = detector.make_labels(node_index, fraud_gstins)
n_fraud = int(labels.sum().item())
n_clean = len(node_index) - n_fraud
print(f"  Labels:     {n_fraud} fraud  /  {n_clean} clean")

# ---------------------------------------------------------------------------
# Step 5: Train GNN
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 5: Training GraphSAGE model …")
print("=" * 60)

history = detector.train_model(data, labels, epochs=100, lr=0.01)

if history.get("used_fallback"):
    print(f"\n  [FALLBACK] {history['fallback_reason']}")
else:
    print(f"\n  Training complete.")
    print(f"  Best val_loss : {history['best_val_loss']:.4f}")
    print(f"  Model saved   : {history['model_path']}")

# ---------------------------------------------------------------------------
# Step 6: Inference
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("Step 6: Running inference …")
print("=" * 60)

predictions = detector.predict_fraud(graph)

high   = {k: v for k, v in predictions.items() if v["fraud_probability"] > 0.5}
medium = {k: v for k, v in predictions.items() if 0.3 <= v["fraud_probability"] <= 0.5}

print(f"  HIGH_RISK   (P > 0.50): {len(high)}")
print(f"  MEDIUM_RISK (P 0.3-0.5): {len(medium)}")
print(f"  Total nodes scored: {len(predictions)}")

print(f"\n  Top-15 highest fraud-probability GSTINs:")
top = sorted(predictions.items(), key=lambda x: x[1]["fraud_probability"], reverse=True)[:15]
for gstin, info in top:
    known = "← known fraud" if gstin in fraud_gstins else ""
    method = info["method"]
    print(
        f"    {gstin}  P={info['fraud_probability']:.4f}"
        f"  [{info['risk_flag']}]  method={method}  {known}"
    )

print(f"\n  Fraud predictions (P > 0.5):")
if high:
    for k, v in sorted(high.items(), key=lambda x: x[1]["fraud_probability"], reverse=True):
        print(f"    {k}: {v}")
else:
    print("    (none above 0.5 threshold)")

print("\n" + "=" * 60)
print("Done.")
print("=" * 60)
