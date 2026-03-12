#!/usr/bin/env python
"""
scripts/download_hf_models.py
Download FinBERT and BERT-NER from HuggingFace Hub only.
No imports from src/ — safe to run before COPY src/ in Docker.
This keeps the model download layer cached across source-only changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "configs" / "model_cache"

os.environ["TRANSFORMERS_CACHE"] = str(CACHE_DIR)
os.environ["HF_HOME"] = str(CACHE_DIR)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  Downloading HuggingFace models → configs/model_cache/")
print("=" * 60)

# Use HF_TOKEN for authenticated downloads if available
_hf_token = os.environ.get("HF_TOKEN") or None
if _hf_token:
    print("  ✓ HF_TOKEN detected — using authenticated downloads.")

import gc

from transformers import AutoTokenizer

# Model classes need torch — import with fallback
try:
    from transformers import (
        AutoModelForTokenClassification,
        AutoModelForSequenceClassification,
    )
    _MODELS_AVAILABLE = True
except ImportError:
    _MODELS_AVAILABLE = False
    print("  ⚠ PyTorch not usable by transformers — downloading tokenizers only.")

print("  → dslim/bert-base-NER …")
AutoTokenizer.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR), token=_hf_token)
if _MODELS_AVAILABLE:
    m = AutoModelForTokenClassification.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR), token=_hf_token)
    del m; gc.collect()

print("  → ProsusAI/finbert …")
AutoTokenizer.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR), token=_hf_token)
if _MODELS_AVAILABLE:
    m = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR), token=_hf_token)
    del m; gc.collect()

print("  ✓ Done.\n")
