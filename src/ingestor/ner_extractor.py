"""
ner_extractor.py — HuggingFace-powered NER and sentiment analysis for intelli_credit.

Models used
-----------
Sentiment : ProsusAI/finbert   (financial domain, 512-token window)
NER       : dslim/bert-base-NER (ORG, PER, LOC, MISC entities)

Both models are cached locally on first download.  Set HF_HOME or
TRANSFORMERS_CACHE in .env / environment to override the cache location.
The default local cache is  <project_root>/configs/model_cache/.

Dependencies
------------
    pip install transformers torch sentencepiece
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("intelli_credit.ingestor.ner_extractor")

# ---------------------------------------------------------------------------
# Cache configuration  ── set before any HuggingFace import
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent   # …/intelli_credit/
_DEFAULT_CACHE = _PROJECT_ROOT / "configs" / "model_cache"
_DEFAULT_CACHE.mkdir(parents=True, exist_ok=True)

# Honour explicit env-var overrides; otherwise use the project-local folder.
if not os.environ.get("TRANSFORMERS_CACHE") and not os.environ.get("HF_HOME"):
    os.environ["TRANSFORMERS_CACHE"] = str(_DEFAULT_CACHE)
    os.environ["HF_HOME"]            = str(_DEFAULT_CACHE)

# ---------------------------------------------------------------------------
# Model identifiers
# ---------------------------------------------------------------------------

_FINBERT_MODEL = "ProsusAI/finbert"
_NER_MODEL     = "dslim/bert-base-NER"

# FinBERT outputs three labels; we map them to a [-1, +1] scalar.
_FINBERT_LABEL_SCORE: dict[str, float] = {
    "positive": +1.0,
    "negative": -1.0,
    "neutral":   0.0,
}

# dslim NER entity types we care about (IOB prefixes stripped by the pipeline)
_NER_TYPES_OF_INTEREST = {"ORG", "PER", "MISC"}

# Regex patterns for MONEY entities (used as a supplement since bert-base-NER
# does not have a dedicated MONEY class)
_MONEY_RE = re.compile(
    r"(?:Rs\.?\s*|INR\s*|₹\s*|USD\s*|\$\s*)"
    r"[\d,]+(?:\.\d+)?\s*"
    r"(?:crore?s?|lakh?s?|billion|bn|million|mn|thousand|k)?\b",
    re.IGNORECASE,
)

# Headers that bound the independent auditor's report section
_AUDITOR_HEADER_RE = re.compile(
    r"(?:INDEPENDENT\s+AUDITOR[''S]*|AUDITOR[''S]*\s+REPORT"
    r"|REPORT\s+OF\s+THE\s+(?:STATUTORY\s+)?AUDITOR)",
    re.IGNORECASE,
)
# Section headers that mark the end of the auditor section
_NEXT_SECTION_RE = re.compile(
    r"(?:BALANCE\s+SHEET|STATEMENT\s+OF\s+(?:PROFIT|FINANCIAL)"
    r"|CASH\s+FLOW|NOTES\s+TO\s+(?:THE\s+)?(?:ACCOUNT|FINANCIAL)"
    r"|BOARD\s+OF\s+DIRECTOR|MANAGEMENT\s+DISCUSSION)",
    re.IGNORECASE,
)

# Sentiment score below which the auditor opinion is flagged
# Import from centralised config; fall back to -0.3 if config not available
try:
    from src.config import AUDITOR_SENTIMENT_THRESHOLD  # noqa: E402
    _AUDITOR_FLAG_THRESHOLD = AUDITOR_SENTIMENT_THRESHOLD
except ImportError:
    _AUDITOR_FLAG_THRESHOLD = -0.3


# ---------------------------------------------------------------------------
# NERExtractor
# ---------------------------------------------------------------------------

class NERExtractor:
    """
    HuggingFace-backed NER and sentiment extractor.

    All heavy model objects are loaded lazily on first use and then cached
    as instance attributes, so repeated calls within one session are cheap.

    Parameters
    ----------
    device : str or int
        PyTorch device string (``"cpu"``, ``"cuda"``, ``"mps"``) or device
        index.  Defaults to ``"cpu"`` for maximum portability.
    finbert_model : str
        HuggingFace model id for FinBERT sentiment.
    ner_model : str
        HuggingFace model id for token-classification NER.
    max_chunk_tokens : int
        Maximum tokens per FinBERT inference pass.  Must be ≤ 512.
    overlap_tokens : int
        Token overlap between consecutive chunks.
    """

    def __init__(
        self,
        device: str | int      = "cpu",
        finbert_model: str     = _FINBERT_MODEL,
        ner_model: str         = _NER_MODEL,
        max_chunk_tokens: int  = 512,
        overlap_tokens: int    = 50,
    ) -> None:
        self.device           = device
        self.finbert_model_id = finbert_model
        self.ner_model_id     = ner_model
        self.max_chunk_tokens = max_chunk_tokens
        self.overlap_tokens   = overlap_tokens

        # Lazily populated
        self._finbert_tokenizer    = None
        self._finbert_pipeline     = None
        self._ner_pipeline         = None

    # ------------------------------------------------------------------
    # Lazy loaders
    # ------------------------------------------------------------------

    def _load_finbert(self) -> None:
        """Load FinBERT tokenizer + sentiment pipeline (idempotent)."""
        if self._finbert_pipeline is not None:
            return
        from transformers import (  # noqa: PLC0415
            AutoTokenizer,
            AutoModelForSequenceClassification,
            pipeline,
        )
        logger.info("Loading FinBERT (%s) …", self.finbert_model_id)
        self._finbert_tokenizer = AutoTokenizer.from_pretrained(
            self.finbert_model_id,
            cache_dir=str(_DEFAULT_CACHE),
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self.finbert_model_id,
            cache_dir=str(_DEFAULT_CACHE),
        )
        self._finbert_pipeline = pipeline(
            "text-classification",
            model=model,
            tokenizer=self._finbert_tokenizer,
            device=self.device,
            top_k=None,             # return scores for all labels
            truncation=True,
            max_length=self.max_chunk_tokens,
        )
        logger.info("FinBERT loaded.")

    def _load_ner(self) -> None:
        """Load bert-base-NER token-classification pipeline (idempotent)."""
        if self._ner_pipeline is not None:
            return
        from transformers import (  # noqa: PLC0415
            AutoTokenizer,
            AutoModelForTokenClassification,
            pipeline,
        )
        logger.info("Loading NER model (%s) …", self.ner_model_id)
        ner_tokenizer = AutoTokenizer.from_pretrained(
            self.ner_model_id,
            cache_dir=str(_DEFAULT_CACHE),
        )
        ner_model = AutoModelForTokenClassification.from_pretrained(
            self.ner_model_id,
            cache_dir=str(_DEFAULT_CACHE),
        )
        self._ner_pipeline = pipeline(
            "ner",
            model=ner_model,
            tokenizer=ner_tokenizer,
            device=self.device,
            aggregation_strategy="simple",  # merges B-/I- tags → full entity spans
        )
        logger.info("NER model loaded.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sentiment_analysis(self, text: str) -> dict[str, Any]:
        """
        Run FinBERT sentiment over *text* using a sliding-window strategy.

        Text is chunked into windows of ``max_chunk_tokens`` tokens with
        ``overlap_tokens`` overlap.  Each chunk receives a weighted sentiment
        score (weight = number of tokens).  The weighted average is returned
        as the overall score.

        Returns
        -------
        dict
            overall_sentiment : "positive" | "negative" | "neutral"
            score             : float in [-1, +1]
            chunk_count       : int
            most_negative_passages : list of up to 3 dicts
              {text, score, token_count}
            most_positive_passages : list of up to 3 dicts
              {text, score, token_count}
        """
        self._load_finbert()

        chunks = self._chunk_text(text)
        if not chunks:
            return self._empty_sentiment_result()

        logger.info("sentiment_analysis: %d chunk(s) to score.", len(chunks))

        scored: list[dict[str, Any]] = []
        for chunk_text, token_count in chunks:
            label, score = self._score_chunk(chunk_text)
            scored.append({
                "text":        chunk_text,
                "label":       label,
                "score":       score,
                "token_count": token_count,
            })

        # Weighted average
        total_tokens  = sum(c["token_count"] for c in scored)
        weighted_sum  = sum(c["score"] * c["token_count"] for c in scored)
        overall_score = round(weighted_sum / max(total_tokens, 1), 4)

        if overall_score > 0.15:
            overall_sentiment = "positive"
        elif overall_score < -0.15:
            overall_sentiment = "negative"
        else:
            overall_sentiment = "neutral"

        # Top passages
        sorted_asc  = sorted(scored, key=lambda x: x["score"])
        sorted_desc = sorted(scored, key=lambda x: x["score"], reverse=True)

        most_negative = [
            {"text": c["text"][:400], "score": c["score"], "token_count": c["token_count"]}
            for c in sorted_asc[:3]
            if c["score"] < -0.5
        ]
        most_positive = [
            {"text": c["text"][:400], "score": c["score"], "token_count": c["token_count"]}
            for c in sorted_desc[:3]
        ]

        logger.info(
            "Sentiment: %s (score=%.4f) over %d chunks / %d tokens.",
            overall_sentiment, overall_score, len(scored), total_tokens,
        )
        return {
            "overall_sentiment":       overall_sentiment,
            "score":                   overall_score,
            "chunk_count":             len(scored),
            "most_negative_passages":  most_negative,
            "most_positive_passages":  most_positive,
        }

    def auditor_sentiment(self, text: str) -> dict[str, Any]:
        """
        Extract the independent auditor's report section and score its sentiment.

        A ``score < -0.3`` triggers ``qualified_opinion_flag = True``.

        Returns
        -------
        dict
            auditor_section_found  : bool
            auditor_text_length    : int
            overall_sentiment      : str
            score                  : float
            qualified_opinion_flag : bool
            most_negative_passages : list
            section_preview        : first 500 chars of the section
        """
        auditor_text = self._extract_auditor_section(text)

        if not auditor_text.strip():
            logger.warning("auditor_sentiment: no auditor section found.")
            return {
                "auditor_section_found":  False,
                "auditor_text_length":    0,
                "overall_sentiment":      "neutral",
                "score":                  0.0,
                "qualified_opinion_flag": False,
                "most_negative_passages": [],
                "section_preview":        "",
            }

        logger.info(
            "auditor_sentiment: auditor section = %d chars.", len(auditor_text)
        )
        sentiment = self.sentiment_analysis(auditor_text)

        return {
            "auditor_section_found":  True,
            "auditor_text_length":    len(auditor_text),
            "overall_sentiment":      sentiment["overall_sentiment"],
            "score":                  sentiment["score"],
            "qualified_opinion_flag": sentiment["score"] < _AUDITOR_FLAG_THRESHOLD,
            "most_negative_passages": sentiment["most_negative_passages"],
            "section_preview":        auditor_text[:500],
        }

    def extract_entities(self, text: str) -> dict[str, Any]:
        """
        Extract named entities using bert-base-NER, supplemented by regex
        for MONEY entities.

        Returns
        -------
        dict
            ORG    : list of unique organisation names
            PERSON : list of unique person names
            MONEY  : list of unique monetary expressions
            MISC   : list of miscellaneous entities
            raw_ner_output : full list of entity dicts from the NER pipeline
        """
        self._load_ner()

        # NER pipeline can struggle with very long text — chunk conservatively
        ner_chunks = self._simple_text_chunks(text, max_chars=2000)
        all_ner: list[dict[str, Any]] = []
        offset = 0
        for chunk in ner_chunks:
            try:
                entities = self._ner_pipeline(chunk)
                for ent in entities:
                    ent["start"] = ent.get("start", 0) + offset
                    ent["end"]   = ent.get("end",   0) + offset
                all_ner.extend(entities)
            except Exception as exc:  # noqa: BLE001
                logger.warning("NER chunk failed: %s", exc)
            offset += len(chunk)

        orgs    = self._unique_entities(all_ner, "ORG")
        persons = self._unique_entities(all_ner, "PER")
        misc    = self._unique_entities(all_ner, "MISC")

        # MONEY: regex (more reliable than MISC for financial amounts)
        money = list({m.group(0).strip() for m in _MONEY_RE.finditer(text)})
        money.sort(key=len, reverse=True)

        logger.info(
            "extract_entities: %d ORG, %d PERSON, %d MONEY, %d MISC.",
            len(orgs), len(persons), len(money), len(misc),
        )
        return {
            "ORG":            orgs,
            "PERSON":         persons,
            "MONEY":          money,
            "MISC":           misc,
            "raw_ner_output": all_ner,
        }

    def analyze(self, text: str) -> dict[str, Any]:
        """
        Full pipeline: sentiment + auditor sentiment + NER in one call.

        Returns
        -------
        dict with keys: sentiment, auditor_sentiment, entities
        """
        return {
            "sentiment":          self.sentiment_analysis(text),
            "auditor_sentiment":  self.auditor_sentiment(text),
            "entities":           self.extract_entities(text),
        }

    # ------------------------------------------------------------------
    # Chunking helpers
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> list[tuple[str, int]]:
        """
        Tokenise *text* and return (chunk_string, token_count) pairs.

        Chunks are created with a sliding window of ``max_chunk_tokens``
        tokens and ``overlap_tokens`` token overlap.
        Special tokens ([CLS], [SEP]) consume 2 tokens; the effective
        content window is therefore ``max_chunk_tokens - 2``.
        """
        tokenizer = self._finbert_tokenizer
        effective = self.max_chunk_tokens - 2   # headroom for [CLS]/[SEP]
        step      = effective - self.overlap_tokens

        if step <= 0:
            step = effective

        # Encode without special tokens to get raw content ids
        ids = tokenizer.encode(text, add_special_tokens=False)

        if not ids:
            return []

        chunks: list[tuple[str, int]] = []
        pos = 0
        while pos < len(ids):
            window_ids  = ids[pos: pos + effective]
            chunk_text  = tokenizer.decode(window_ids, skip_special_tokens=True)
            token_count = len(window_ids)
            if chunk_text.strip():
                chunks.append((chunk_text, token_count))
            pos += step
            if pos >= len(ids):
                break

        return chunks

    @staticmethod
    def _simple_text_chunks(text: str, max_chars: int = 2000) -> list[str]:
        """Split text into plain character-based chunks for the NER pipeline."""
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            # Try to break at a sentence boundary
            region = text[start:end]
            break_at = max(
                region.rfind(". "),
                region.rfind("\n"),
            )
            if break_at > max_chars // 2:
                end = start + break_at + 1
            chunks.append(text[start:end])
            start = end
        return [c for c in chunks if c.strip()]

    # ------------------------------------------------------------------
    # Sentiment helpers
    # ------------------------------------------------------------------

    def _score_chunk(self, chunk_text: str) -> tuple[str, float]:
        """
        Run FinBERT on a single pre-chunked string.

        Returns (dominant_label, scalar_score).
        The scalar is the probability-weighted sum across all three labels.
        """
        try:
            result = self._finbert_pipeline(chunk_text)
            # pipeline with top_k=None returns [[{label, score}, ...]]
            label_scores: list[dict] = result[0] if isinstance(result[0], list) else result

            scalar = 0.0
            dominant_label = "neutral"
            max_prob = -1.0
            for item in label_scores:
                label = item["label"].lower()
                prob  = float(item["score"])
                multiplier = _FINBERT_LABEL_SCORE.get(label, 0.0)
                scalar += multiplier * prob
                if prob > max_prob:
                    max_prob       = prob
                    dominant_label = label

            return dominant_label, round(scalar, 4)

        except Exception as exc:  # noqa: BLE001
            logger.warning("Chunk scoring failed: %s", exc)
            return "neutral", 0.0

    @staticmethod
    def _empty_sentiment_result() -> dict[str, Any]:
        return {
            "overall_sentiment":       "neutral",
            "score":                   0.0,
            "chunk_count":             0,
            "most_negative_passages":  [],
            "most_positive_passages":  [],
        }

    # ------------------------------------------------------------------
    # Auditor-section extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_auditor_section(text: str) -> str:
        """
        Return the substring of *text* that contains the independent
        auditor's report.

        Searches for an auditor-header match and extracts text until the
        next major section header or up to 8 000 characters, whichever
        comes first.
        """
        header_match = _AUDITOR_HEADER_RE.search(text)
        if not header_match:
            return ""

        start = header_match.start()
        # Search for the end of this section within a reasonable window
        window = text[start: start + 12_000]

        end_match = None
        for m in _NEXT_SECTION_RE.finditer(window):
            if m.start() > 200:   # skip if another header immediately follows
                end_match = m
                break

        end = start + (end_match.start() if end_match else min(8_000, len(window)))
        return text[start:end].strip()

    # ------------------------------------------------------------------
    # NER post-processing
    # ------------------------------------------------------------------

    @staticmethod
    def _unique_entities(
        ner_output: list[dict[str, Any]], entity_type: str
    ) -> list[str]:
        """
        Collect unique entity spans for *entity_type* from the aggregated
        NER pipeline output (``aggregation_strategy="simple"``).

        ``entity_group`` keys produced by ``aggregation_strategy="simple"``
        strip the B-/I- prefix and return just ``"ORG"``, ``"PER"``, etc.
        """
        seen: dict[str, float] = {}
        for ent in ner_output:
            group = ent.get("entity_group", "").upper()
            if group != entity_type.upper():
                continue
            word  = str(ent.get("word", "")).strip()
            score = float(ent.get("score", 0.0))
            # Keep the highest-confidence span for each normalised surface form
            norm = " ".join(word.split())
            if norm and (norm not in seen or score > seen[norm]):
                seen[norm] = score

        # Sort by descending confidence
        return [k for k, _ in sorted(seen.items(), key=lambda x: -x[1])]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_extractor: NERExtractor | None = None


def get_extractor(**kwargs) -> NERExtractor:
    """Return the module-level NERExtractor singleton."""
    global _extractor  # noqa: PLW0603
    if _extractor is None:
        _extractor = NERExtractor(**kwargs)
    return _extractor


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def sentiment_analysis(text: str, **kwargs) -> dict[str, Any]:
    """One-shot FinBERT sentiment analysis."""
    return get_extractor(**kwargs).sentiment_analysis(text)


def auditor_sentiment(text: str, **kwargs) -> dict[str, Any]:
    """One-shot auditor-section sentiment analysis."""
    return get_extractor(**kwargs).auditor_sentiment(text)


def extract_entities(text: str, **kwargs) -> dict[str, Any]:
    """One-shot NER entity extraction."""
    return get_extractor(**kwargs).extract_entities(text)


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    import logging as _logging

    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    # Suppress noisy HuggingFace progress logs
    _logging.getLogger("transformers").setLevel(_logging.WARNING)
    _logging.getLogger("torch").setLevel(_logging.WARNING)

    # Accept optional path to a PDFParser JSON dump
    text_to_test: str

    if len(sys.argv) >= 2:
        import pathlib
        data = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
        text_to_test = data.get("raw_text", "")
    else:
        text_to_test = """
Reliance Industries Limited reported total revenue of Rs. 9,01,532 crore
for FY2024, representing a modest growth of 2.3% over the previous year.
EBITDA stood at Rs. 1,78,677 crore with margins improving to 19.8%.

INDEPENDENT AUDITOR'S REPORT
To the Members of Reliance Industries Limited

We have audited the standalone financial statements of Reliance Industries
Limited ("the Company"), which comprise the Balance Sheet as at 31st March 2024,
the Statement of Profit and Loss and the Statement of Cash Flows for the year
ended on that date.

In our opinion and to the best of our information, the aforesaid standalone
financial statements give the information required by the Act and give a true
and fair view. The company has maintained adequate internal financial controls.
No qualified or adverse remarks were noted during the audit.

BALANCE SHEET
Total Assets: Rs. 17,47,178 crore
"""

    extractor = NERExtractor()

    print("\n--- Sentiment Analysis ---")
    sent = extractor.sentiment_analysis(text_to_test)
    summary = {k: v for k, v in sent.items()
               if k not in ("most_negative_passages", "most_positive_passages")}
    print(json.dumps(summary, indent=2))
    print(f"most_positive[0]: {sent['most_positive_passages'][0]['text'][:120] if sent['most_positive_passages'] else 'none'}")

    print("\n--- Auditor Sentiment ---")
    aud = extractor.auditor_sentiment(text_to_test)
    print(json.dumps(
        {k: v for k, v in aud.items() if k != "most_negative_passages"},
        indent=2,
    ))

    print("\n--- Entity Extraction ---")
    ents = extractor.extract_entities(text_to_test)
    print(json.dumps(
        {k: v for k, v in ents.items() if k != "raw_ner_output"},
        indent=2,
        ensure_ascii=False,
    ))

    print("\n✓ NERExtractor smoke-test complete.")
