"""Syntax-check both new files without importing Streamlit."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = [
    root / "src" / "scorer" / "qualitative_scorer.py",
    root / "src" / "ui"     / "qualitative_portal.py",
]

for f in files:
    ast.parse(f.read_text(encoding="utf-8"))
    print(f"  SYNTAX OK  {f.relative_to(root)}")

print("\nAll files syntax-clean.")
