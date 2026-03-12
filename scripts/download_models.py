#!/usr/bin/env python
"""
scripts/download_models.py — Download ML models that are gitignored.

Run once on a fresh deploy or new machine:
    python scripts/download_models.py

Downloads:
  1. HuggingFace FinBERT + BERT-NER → configs/model_cache/
  2. Trains a fresh credit_scorer.pkl if missing (uses generate_training_data)
  3. Trains a fresh gnn_fraud_detector.pt if missing
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 encoding errors
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "configs" / "model_cache"
MODELS_DIR = PROJECT_ROOT / "models"

sys.path.insert(0, str(PROJECT_ROOT))


def download_huggingface_models():
    """Download FinBERT and BERT-NER from HuggingFace Hub."""
    os.environ.setdefault("TRANSFORMERS_CACHE", str(CACHE_DIR))
    os.environ.setdefault("HF_HOME", str(CACHE_DIR))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/3] Downloading HuggingFace models → configs/model_cache/")

    from transformers import AutoTokenizer, AutoModelForTokenClassification, AutoModelForSequenceClassification

    print("      → dslim/bert-base-NER …")
    AutoTokenizer.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR))
    AutoModelForTokenClassification.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR))

    print("      → ProsusAI/finbert …")
    AutoTokenizer.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR))
    AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR))

    print("      ✓ HuggingFace models cached.\n")


def ensure_credit_scorer():
    """Train a credit scorer if credit_scorer.pkl is missing."""
    pkl_path = MODELS_DIR / "credit_scorer.pkl"
    if pkl_path.exists():
        print("[2/3] credit_scorer.pkl already exists — skipping.\n")
        return

    print("[2/3] Training credit_scorer.pkl …")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # Generate training data first
        training_csv = PROJECT_ROOT / "data" / "silver" / "training_data.csv"
        if not training_csv.exists():
            print("      Generating training data …")
            (PROJECT_ROOT / "data" / "silver").mkdir(parents=True, exist_ok=True)
            from tests.generate_training_data import main as gen_data
            gen_data()

        from src.scorer.credit_scorer import CreditScorer
        scorer = CreditScorer()
        if training_csv.exists():
            scorer.train(str(training_csv))
            print(f"      ✓ Saved → {pkl_path}\n")
        else:
            print("      ⚠  No training data found — scorer will use rule-based fallback.\n")
    except Exception as exc:
        print(f"      ⚠  Could not train scorer (non-fatal): {exc}\n")


def ensure_gnn_model():
    """Train a GNN if gnn_fraud_detector.pt is missing."""
    pt_path = MODELS_DIR / "gnn_fraud_detector.pt"
    if pt_path.exists():
        print("[3/3] gnn_fraud_detector.pt already exists — skipping.\n")
        return

    print("[3/3] Training gnn_fraud_detector.pt …")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import json
        from src.gst.data_generator import GSTDataGenerator
        from src.gst.graph_builder import TransactionGraphBuilder
        from src.gst.gnn_detector import CircularTradingDetector, collect_fraud_gstins, GST_RAW_DIR

        # Step 1: Generate synthetic GST data
        GST_RAW_DIR.mkdir(parents=True, exist_ok=True)
        gen = GSTDataGenerator()
        companies_clean = ["COMP_A_RELIANCE", "COMP_B_MEDIUM"]
        companies_fraud = ["COMP_C_FRAUD", "COMP_D_FRAUD2", "COMP_E_FRAUD3"]

        for name in companies_clean:
            if not (GST_RAW_DIR / f"{name}_gstr1.json").exists():
                print(f"      Generating {name} (clean) …")
                gen.generate_company_data(name, inject_fraud=False)
        for name in companies_fraud:
            if not (GST_RAW_DIR / f"{name}_gstr1.json").exists():
                print(f"      Generating {name} (fraud) …")
                gen.generate_company_data(name, inject_fraud=True)

        # Step 2: Build transaction graph
        builder = TransactionGraphBuilder()
        all_data = {}
        for company in companies_clean + companies_fraud:
            all_data[company] = {
                "gstr1":  json.load(open(GST_RAW_DIR / f"{company}_gstr1.json")),
                "gstr2a": json.load(open(GST_RAW_DIR / f"{company}_gstr2a.json")),
                "gstr3b": json.load(open(GST_RAW_DIR / f"{company}_gstr3b.json")),
            }
        graph = builder.build_graph(list(all_data.values()))
        print(f"      Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")

        # Step 3: Collect fraud labels
        fraud_gstins = collect_fraud_gstins(GST_RAW_DIR)
        print(f"      Fraud GSTINs: {len(fraud_gstins)}")

        # Step 4: Convert to PyG format + train
        detector = CircularTradingDetector()
        data, node_index = detector.convert_to_pyg_data(graph)
        labels = detector.make_labels(node_index, fraud_gstins)
        history = detector.train_model(data, labels, epochs=100, lr=0.01)

        if history.get("used_fallback"):
            print(f"      ⚠  GNN used fallback: {history.get('fallback_reason', 'unknown')}\n")
        else:
            print(f"      ✓ Saved → {pt_path}\n")
    except Exception as exc:
        print(f"      ⚠  Could not train GNN (non-fatal): {exc}\n")


if __name__ == "__main__":
    print("=" * 60)
    print("  Intelli-Credit — Model Setup")
    print("=" * 60 + "\n")

    download_huggingface_models()
    ensure_credit_scorer()
    ensure_gnn_model()

    print("=" * 60)
    print("  Done! You can now start the API:  python run_api.py")
    print("=" * 60)
