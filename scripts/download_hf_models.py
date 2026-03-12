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

from transformers import (
    AutoTokenizer,
    AutoModelForTokenClassification,
    AutoModelForSequenceClassification,
)

print("  → dslim/bert-base-NER …")
AutoTokenizer.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR))
AutoModelForTokenClassification.from_pretrained("dslim/bert-base-NER", cache_dir=str(CACHE_DIR))

print("  → ProsusAI/finbert …")
AutoTokenizer.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR))
AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert", cache_dir=str(CACHE_DIR))

print("  ✓ Done.\n")
