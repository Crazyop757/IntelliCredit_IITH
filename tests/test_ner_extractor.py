"""
test_ner_extractor.py — Unit tests for NERExtractor.

Tests FinBERT sentiment analysis and BERT-NER entity extraction using
mocked HuggingFace pipelines (no GPU or model download required).

Usage:
    python tests/test_ner_extractor.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── ANSI helpers ──────────────────────────────────────────────────────────────
_GREEN = "\033[92m"
_RED   = "\033[91m"
_CYAN  = "\033[96m"
_RESET = "\033[0m"
_BOLD  = "\033[1m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, expr: bool, detail: str = ""):
    tag = f"{_GREEN}PASS{_RESET}" if expr else f"{_RED}FAIL{_RESET}"
    _results.append((name, expr, detail))
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail and not expr else ""))


def report():
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"\n{_BOLD}{'='*60}")
    print(f"  {_GREEN}{passed} passed{_RESET}, {_RED}{failed} failed{_RESET}")
    print(f"{'='*60}{_RESET}")
    return 0 if failed == 0 else 1


# ── Imports ───────────────────────────────────────────────────────────────────
from src.ingestor.ner_extractor import (
    NERExtractor,
    _MONEY_RE,
    _AUDITOR_HEADER_RE,
    _NEXT_SECTION_RE,
)


def test_money_regex():
    """MONEY_RE should match common Indian and US monetary amounts."""
    print(f"\n{_CYAN}{_BOLD}── Money regex ──{_RESET}")
    positives = [
        "Rs. 1,23,456.78 crore",
        "INR 50 lakh",
        "₹10,000",
        "USD 1.5 million",
        "$250,000",
        "Rs 500 crores",
    ]
    for s in positives:
        check(f"Matches: {s!r}", _MONEY_RE.search(s) is not None)

    negatives = ["hello world", "42 items", "EBITDA margin 10.5%"]
    for s in negatives:
        check(f"No match: {s!r}", _MONEY_RE.search(s) is None)


def test_auditor_header_regex():
    """AUDITOR_HEADER_RE should match common auditor report headers."""
    print(f"\n{_CYAN}{_BOLD}── Auditor header regex ──{_RESET}")
    positives = [
        "INDEPENDENT AUDITOR'S REPORT",
        "Report of the Statutory Auditor",
        "AUDITOR'S REPORT",
    ]
    for s in positives:
        check(f"Matches: {s!r}", _AUDITOR_HEADER_RE.search(s) is not None)


def test_next_section_regex():
    """NEXT_SECTION_RE should match section headers that end the auditor section."""
    print(f"\n{_CYAN}{_BOLD}── Next section regex ──{_RESET}")
    positives = [
        "BALANCE SHEET",
        "Statement of Profit and Loss",
        "Cash Flow Statement",
        "Notes to the Financial Statements",
    ]
    for s in positives:
        check(f"Matches: {s!r}", _NEXT_SECTION_RE.search(s) is not None)


def test_sentiment_empty_input():
    """sentiment_analysis on empty string should return neutral defaults."""
    print(f"\n{_CYAN}{_BOLD}── Sentiment empty input ──{_RESET}")
    extractor = NERExtractor()

    # Mock the finbert loader and set a mock tokenizer so _chunk_text works
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = []

    with patch.object(extractor, '_load_finbert'):
        extractor._finbert_tokenizer = mock_tokenizer
        result = extractor.sentiment_analysis("")
        check("Returns dict", isinstance(result, dict))
        check("overall_sentiment = neutral", result.get("overall_sentiment") == "neutral")
        check("score = 0.0", result.get("score") == 0.0)
        check("chunk_count = 0", result.get("chunk_count") == 0)


def test_sentiment_with_mocked_pipeline():
    """sentiment_analysis with mocked FinBERT pipeline should aggregate correctly."""
    print(f"\n{_CYAN}{_BOLD}── Sentiment with mocked pipeline ──{_RESET}")
    extractor = NERExtractor()

    # Build a mock pipeline
    mock_tokenizer = MagicMock()
    # Return mock encoding with 100 tokens
    mock_encoding = MagicMock()
    mock_encoding.input_ids = list(range(100))
    mock_tokenizer.return_value = mock_encoding
    mock_tokenizer.encode = lambda text, **kw: list(range(min(len(text.split()), 100)))
    mock_tokenizer.decode = lambda ids, **kw: " ".join(["word"] * len(ids))

    # Mock FinBERT pipeline to return positive sentiment
    mock_pipeline = MagicMock()
    mock_pipeline.return_value = [[
        {"label": "positive", "score": 0.8},
        {"label": "neutral", "score": 0.15},
        {"label": "negative", "score": 0.05},
    ]]

    extractor._finbert_pipeline = mock_pipeline
    extractor._finbert_tokenizer = mock_tokenizer

    # Use short text so only one chunk is created
    text = "The company shows strong revenue growth and excellent margins."
    result = extractor.sentiment_analysis(text)

    check("Returns dict", isinstance(result, dict))
    check("score is numeric", isinstance(result.get("score", None), (int, float)))
    check("overall_sentiment present", "overall_sentiment" in result)


def test_extract_entities_empty():
    """extract_entities on empty string should return empty results."""
    print(f"\n{_CYAN}{_BOLD}── Extract entities empty input ──{_RESET}")
    extractor = NERExtractor()

    # Mock the NER pipeline to return empty list for empty input
    mock_ner_pipeline = MagicMock(return_value=[])

    with patch.object(extractor, '_load_ner'):
        extractor._ner_pipeline = mock_ner_pipeline
        result = extractor.extract_entities("")
        check("Returns dict", isinstance(result, dict))
        check("ORG is empty list", result.get("ORG") == [])
        check("PERSON is empty list", result.get("PERSON") == [])
        check("MONEY is empty list", result.get("MONEY") == [])
        check("MISC is empty list", result.get("MISC") == [])


def test_extractor_init_defaults():
    """NERExtractor init should set default device and model IDs."""
    print(f"\n{_CYAN}{_BOLD}── NERExtractor init defaults ──{_RESET}")
    extractor = NERExtractor()
    check("Default device = cpu", extractor.device == "cpu")
    check("FinBERT model = ProsusAI/finbert",
          extractor.finbert_model_id == "ProsusAI/finbert")
    check("NER model = dslim/bert-base-NER",
          extractor.ner_model_id == "dslim/bert-base-NER")
    check("max_chunk_tokens = 512", extractor.max_chunk_tokens == 512)
    check("_finbert_pipeline is None initially",
          extractor._finbert_pipeline is None)
    check("_ner_pipeline is None initially",
          extractor._ner_pipeline is None)


def test_auditor_flag_threshold():
    """_AUDITOR_FLAG_THRESHOLD should match config value."""
    print(f"\n{_CYAN}{_BOLD}── Auditor threshold from config ──{_RESET}")
    from src.ingestor.ner_extractor import _AUDITOR_FLAG_THRESHOLD
    from src.config import AUDITOR_SENTIMENT_THRESHOLD
    check("Threshold matches config",
          _AUDITOR_FLAG_THRESHOLD == AUDITOR_SENTIMENT_THRESHOLD,
          f"got {_AUDITOR_FLAG_THRESHOLD} vs config {AUDITOR_SENTIMENT_THRESHOLD}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{_BOLD}{'='*60}")
    print(f"  NERExtractor Unit Tests")
    print(f"{'='*60}{_RESET}")

    test_money_regex()
    test_auditor_header_regex()
    test_next_section_regex()
    test_sentiment_empty_input()
    test_sentiment_with_mocked_pipeline()
    test_extract_entities_empty()
    test_extractor_init_defaults()
    test_auditor_flag_threshold()

    exit_code = report()
    sys.exit(exit_code)
