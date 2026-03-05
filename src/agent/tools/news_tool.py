"""
news_tool.py — News intelligence tool for intelli_credit.

Fetches and analyses recent news about a company and its promoters using the
Tavily search API, then scores each article with FinBERT sentiment and
classifies the risk type.

Public API
----------
    tool = NewsIntelligenceTool()
    report = tool.search_company_news("Tata Steel", ["Ratan Tata", "N Chandrasekaran"])
    # report contains: articles, news_risk_score, negative_article_count,
    #                  most_alarming_headline, source_credibility_score, risk_tags
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Honour the shared model-cache directory used by NERExtractor
_DEFAULT_CACHE = _PROJECT_ROOT / "configs" / "model_cache"
_DEFAULT_CACHE.mkdir(parents=True, exist_ok=True)
if not os.environ.get("TRANSFORMERS_CACHE") and not os.environ.get("HF_HOME"):
    os.environ["TRANSFORMERS_CACHE"] = str(_DEFAULT_CACHE)
    os.environ["HF_HOME"]            = str(_DEFAULT_CACHE)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger("intelli_credit.agent.tools.news_tool")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Lookback window for news (24 months from today)
_LOOKBACK_MONTHS = 24

# FinBERT model reused from NERExtractor
_FINBERT_MODEL = "ProsusAI/finbert"

# Source-credibility map (domain substring → score)
_SOURCE_CREDIBILITY: dict[str, float] = {
    "economictimes":     0.9,
    "livemint":          0.9,
    "thehindu":          0.9,
    "hindu":             0.9,
    "businessstandard":  0.9,
    "business-standard": 0.9,
    "moneycontrol":      0.85,
    "financialexpress":  0.85,
    "ndtv":              0.85,
    "reuters":           0.9,
    "bloomberg":         0.9,
    "ft.com":            0.9,
    "wsj.com":           0.9,
}
_DEFAULT_CREDIBILITY = 0.6

# Risk-type keyword mapping: label → list of regex patterns (case-insensitive)
_RISK_TYPE_PATTERNS: dict[str, list[str]] = {
    "FRAUD": [
        r"\bfraud\b", r"\bscam\b", r"\bmisappropriat", r"\bembezzl",
        r"\bmoney\s+launder", r"\bhawala\b", r"\bbenami\b",
        r"\bfictitious\b", r"\bforensic\s+audit\b",
    ],
    "REGULATORY": [
        r"\bRBI\b", r"\bSEBI\b", r"\bNCLT\b", r"\bED\b(?:\s+notice|\s+raid)?",
        r"\bSFIO\b", r"\bCBI\b", r"\bEnforcement\s+Directorate\b",
        r"\bregulatory\s+action\b", r"\bshow[- ]?cause\b", r"\bsuspend",
        r"\bpenalt(?:y|ies)\b", r"\bfine\b.*\bregulat",
    ],
    "LITIGATION": [
        r"\bcourtcase\b", r"\bcourt\s+case\b", r"\blawsuit\b",
        r"\blitigation\b", r"\barbitration\b", r"\bSARFAESI\b",
        r"\binsolvency\b", r"\bIBC\b", r"\badjudicat",
        r"\bcheque\s+bounce\b", r"\bcheque\s+dishonour",
    ],
    "OPERATIONAL": [
        r"\bNPA\b", r"\bdefault\b", r"\bdowngrade\b", r"\bcredit\s+watch\b",
        r"\bplant\s+shut", r"\bstrike\b", r"\blockout\b",
        r"\bsupply\s+chain\b", r"\bshutdown\b", r"\brestructur",
    ],
    "MANAGEMENT": [
        r"\bCEO\b.*(?:resign|quit|exit|sack)", r"\bMD\b.*(?:resign|quit|exit)",
        r"\bpromoter\b.*(?:sell|offload|pledge)", r"\bboard\s+resign",
        r"\binsider\s+trad", r"\bpromoter\s+fraud",
        r"\bkey\s+managerial", r"\bcorporate\s+governance",
    ],
    "MARKET": [
        r"\bstock\s+(?:crash|plunge|fall|drop|rally)\b",
        r"\bshare\s+(?:crash|plunge|fall|drop)\b",
        r"\bmarket\s+cap\b.*(?:loss|erase|wipe)",
        r"\bearnings\s+miss\b", r"\bprofit\s+warning\b",
        r"\bquarterly\s+(?:loss|results)\b",
    ],
}


# ===========================================================================
# NewsIntelligenceTool
# ===========================================================================

class NewsIntelligenceTool:
    """
    Fetch, score, and classify recent news for a company and its promoters.

    Parameters
    ----------
    tavily_api_key : str | None
        Tavily API key.  Falls back to the ``TAVILY_API_KEY`` environment
        variable when not supplied.
    device : str
        PyTorch device passed to FinBERT (``"cpu"``, ``"cuda"``, ``"mps"``).
    """

    def __init__(
        self,
        tavily_api_key: str | None = None,
        device: str = "cpu",
    ) -> None:
        self._api_key = tavily_api_key or _TAVILY_API_KEY
        self._device  = device

        # Lazily initialised
        self._tavily_client       = None
        self._finbert_pipeline    = None
        self._finbert_tokenizer   = None

    # ------------------------------------------------------------------
    # Top-level public method
    # ------------------------------------------------------------------

    def search_company_news(
        self,
        company_name:   str,
        promoter_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Full news-intelligence pipeline for *company_name*.

        Steps
        -----
        1. Search Tavily for risk-related and earnings news about the company.
        2. Search Tavily for each promoter name individually.
        3. Deduplicate articles by URL.
        4. Score sentiment (FinBERT) per article.
        5. Classify risk type per article.
        6. Aggregate into ``news_risk_score``, ``source_credibility_score``,
           ``negative_article_count``, ``most_alarming_headline``.
        7. Return the complete news intelligence report dict.

        Parameters
        ----------
        company_name :
            Human-readable company name (e.g. "Tata Steel").
        promoter_names :
            Optional list of promoter / director names.

        Returns
        -------
        dict — full news intelligence report (see module docstring).
        """
        promoter_names = promoter_names or []

        # ── 1 & 2. Fetch articles ─────────────────────────────────────
        raw_articles: list[dict[str, Any]] = []

        # Company risk query
        raw_articles.extend(
            self._tavily_search(
                f"{company_name} fraud OR NPA OR litigation OR RBI notice OR NCLT",
                topic="news",
            )
        )
        # Company earnings / results query
        raw_articles.extend(
            self._tavily_search(
                f"{company_name} quarterly results OR earnings",
                topic="news",
            )
        )
        # Per-promoter queries
        for name in promoter_names:
            raw_articles.extend(
                self._tavily_search(
                    f"{name} court case OR defaulter OR fraud OR cheque bounce",
                    topic="news",
                )
            )

        # ── 3. Deduplicate by URL ─────────────────────────────────────
        seen_urls: set[str] = set()
        articles: list[dict[str, Any]] = []
        for art in raw_articles:
            url = art.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                articles.append(self._normalise_article(art))

        logger.info(
            "[%s] %d unique articles fetched (%d raw).",
            company_name, len(articles), len(raw_articles),
        )

        # ── 4. Sentiment scoring ──────────────────────────────────────
        articles = self.compute_news_sentiment(articles)

        # ── 5. Risk-type classification ───────────────────────────────
        articles = self.classify_risk_type(articles)

        # ── 6 & 7. Aggregate and return ───────────────────────────────
        return self._build_report(company_name, promoter_names, articles)

    # ------------------------------------------------------------------
    # Step 4: FinBERT sentiment per article
    # ------------------------------------------------------------------

    def compute_news_sentiment(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Score each article with FinBERT and attach sentiment fields.

        Added fields per article
        ------------------------
        sentiment_label  : "positive" | "negative" | "neutral"
        sentiment_score  : float in [-1, +1]

        Also computes aggregate stats and attaches them as
        ``_aggregate`` on the returned list object (accessed via
        ``list._aggregate`` — NOT a dict key; used internally by
        ``_build_report``).

        Returns the same list with sentiment fields filled in.
        """
        if not articles:
            return articles

        self._load_finbert()

        for art in articles:
            text = f"{art.get('title', '')}. {art.get('snippet', '')}"
            label, score = self._finbert_score(text.strip())
            art["sentiment_label"] = label
            art["sentiment_score"] = score

        return articles

    # ------------------------------------------------------------------
    # Step 6: Risk-type classification
    # ------------------------------------------------------------------

    def classify_risk_type(
        self, articles: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Tag each article with one or more risk types.

        Tags assigned: ``FRAUD``, ``REGULATORY``, ``LITIGATION``,
        ``OPERATIONAL``, ``MANAGEMENT``, ``MARKET``.

        Adds ``risk_tags: list[str]`` to each article dict.
        """
        for art in articles:
            haystack = f"{art.get('title', '')} {art.get('snippet', '')}"
            tags: list[str] = []
            for risk_type, patterns in _RISK_TYPE_PATTERNS.items():
                for pat in patterns:
                    if re.search(pat, haystack, re.IGNORECASE):
                        tags.append(risk_type)
                        break   # one match per type is enough
            art["risk_tags"] = tags if tags else ["MARKET"]   # default bucket
        return articles

    # ------------------------------------------------------------------
    # Report assembly
    # ------------------------------------------------------------------

    def _build_report(
        self,
        company_name:   str,
        promoter_names: list[str],
        articles:       list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate article-level signals into the top-level report."""

        negative = [
            a for a in articles
            if a.get("sentiment_label") == "negative"
        ]
        negative_count = len(negative)

        # news_risk_score: 0–10, driven by negative fraction + severity
        if articles:
            neg_fraction  = negative_count / len(articles)
            avg_neg_score = (
                sum(abs(a["sentiment_score"]) for a in negative) / negative_count
                if negative_count else 0.0
            )
            # Weighted: fraction × 7 + depth × 3
            raw = neg_fraction * 7.0 + avg_neg_score * 3.0
            news_risk_score = round(min(raw, 10.0), 2)
        else:
            news_risk_score = 0.0

        # Most alarming headline: lowest (most negative) sentiment_score
        alarming: dict[str, Any] = {}
        if articles:
            worst = min(articles, key=lambda a: a.get("sentiment_score", 0.0))
            if worst.get("sentiment_score", 0.0) < 0:
                alarming = {
                    "title":           worst.get("title", ""),
                    "url":             worst.get("url", ""),
                    "sentiment_score": worst.get("sentiment_score"),
                    "source_domain":   worst.get("source_domain", ""),
                    "risk_tags":       worst.get("risk_tags", []),
                }

        # source_credibility_score: weighted average by credibility weight
        if articles:
            cred_scores = [_domain_credibility(a.get("source_domain", "")) for a in articles]
            source_credibility_score = round(sum(cred_scores) / len(cred_scores), 3)
        else:
            source_credibility_score = 0.0

        # Risk-tag frequency
        tag_freq: dict[str, int] = {}
        for art in articles:
            for tag in art.get("risk_tags", []):
                tag_freq[tag] = tag_freq.get(tag, 0) + 1

        # High-risk article list (negative sentiment + non-MARKET tag)
        high_risk_articles = [
            {
                "title":           a.get("title"),
                "url":             a.get("url"),
                "sentiment_score": a.get("sentiment_score"),
                "risk_tags":       a.get("risk_tags"),
                "source_domain":   a.get("source_domain"),
                "publication_date": a.get("publication_date"),
            }
            for a in articles
            if a.get("sentiment_label") == "negative"
            and any(t != "MARKET" for t in a.get("risk_tags", ["MARKET"]))
        ]
        high_risk_articles.sort(key=lambda x: x.get("sentiment_score", 0.0))

        return {
            # ── Identity ─────────────────────────────────────────────
            "company_name":          company_name,
            "promoter_names":        promoter_names,
            "analysed_at":           datetime.now(tz=timezone.utc).isoformat(),
            "lookback_months":       _LOOKBACK_MONTHS,

            # ── Aggregate scores ──────────────────────────────────────
            "news_risk_score":         news_risk_score,        # 0–10
            "negative_article_count":  negative_count,
            "total_article_count":     len(articles),
            "most_alarming_headline":  alarming,
            "source_credibility_score": source_credibility_score,
            "risk_tag_frequency":      tag_freq,

            # ── Detailed article list ─────────────────────────────────
            "high_risk_articles":    high_risk_articles,
            "articles":              articles,
        }

    # ------------------------------------------------------------------
    # Tavily search helper
    # ------------------------------------------------------------------

    def _tavily_search(
        self,
        query:          str,
        topic:          str = "news",
        max_results:    int = 10,
    ) -> list[dict[str, Any]]:
        """
        Call Tavily ``search`` and return a flat list of raw result dicts.

        Uses ``days`` parameter to restrict results to the last 24 months.
        Falls back to an empty list on any API error.
        """
        if not self._api_key:
            logger.warning("No Tavily API key configured — skipping search for: %s", query)
            return []

        self._load_tavily()
        try:
            # Tavily's ``days`` param: restrict to last N days
            lookback_days = _LOOKBACK_MONTHS * 30
            response = self._tavily_client.search(
                query=query,
                topic=topic,
                max_results=max_results,
                days=lookback_days,
                include_raw_content=False,
            )
            results: list[dict] = response.get("results", [])
            logger.debug("Tavily[%r] → %d results.", query[:60], len(results))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavily search failed for %r: %s", query[:60], exc)
            return []

    # ------------------------------------------------------------------
    # Article normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_article(raw: dict[str, Any]) -> dict[str, Any]:
        """
        Map a raw Tavily result dict to the canonical article schema.

        Schema
        ------
        title            : str
        url              : str
        snippet          : str   (content excerpt, ≤ 600 chars)
        publication_date : str | None  (ISO-8601 or raw string)
        source_domain    : str
        """
        url    = raw.get("url", "")
        domain = _extract_domain(url)

        # Tavily may return ``published_date`` or ``date`` depending on version
        pub_date = (
            raw.get("published_date")
            or raw.get("date")
            or None
        )

        # Truncate content to a concise snippet
        content = raw.get("content") or raw.get("raw_content") or ""
        snippet = content[:600].strip()

        return {
            "title":            raw.get("title", "").strip(),
            "url":              url,
            "snippet":          snippet,
            "publication_date": pub_date,
            "source_domain":    domain,
            # Sentinel fields filled in later
            "sentiment_label":  None,
            "sentiment_score":  None,
            "risk_tags":        [],
        }

    # ------------------------------------------------------------------
    # FinBERT helpers
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
        logger.info("Loading FinBERT (%s) …", _FINBERT_MODEL)
        self._finbert_tokenizer = AutoTokenizer.from_pretrained(
            _FINBERT_MODEL, cache_dir=str(_DEFAULT_CACHE)
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            _FINBERT_MODEL, cache_dir=str(_DEFAULT_CACHE)
        )
        self._finbert_pipeline = pipeline(
            "text-classification",
            model=model,
            tokenizer=self._finbert_tokenizer,
            device=self._device,
            top_k=None,
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT loaded.")

    def _finbert_score(self, text: str) -> tuple[str, float]:
        """
        Score a short text snippet with FinBERT.

        Returns
        -------
        (label, score) where label ∈ {"positive","negative","neutral"}
        and score ∈ [-1, +1].
        """
        if not text.strip():
            return "neutral", 0.0
        try:
            results = self._finbert_pipeline(text[:512])
            # pipeline returns [[{label, score}, ...]] when top_k=None
            label_scores: list[dict] = results[0] if isinstance(results[0], list) else results
            # Pick the label with the highest probability
            best = max(label_scores, key=lambda x: x["score"])
            label = best["label"].lower()
            # Map to signed numeric scalar
            _label_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            numeric = _label_map.get(label, 0.0) * best["score"]
            return label, round(numeric, 4)
        except Exception as exc:  # noqa: BLE001
            logger.debug("FinBERT scoring failed: %s", exc)
            return "neutral", 0.0

    # ------------------------------------------------------------------
    # Tavily client loader
    # ------------------------------------------------------------------

    def _load_tavily(self) -> None:
        """Initialise TavilyClient (idempotent)."""
        if self._tavily_client is not None:
            return
        try:
            from tavily import TavilyClient  # noqa: PLC0415
            self._tavily_client = TavilyClient(api_key=self._api_key)
            logger.info("TavilyClient initialised.")
        except ImportError:
            raise ImportError(
                "tavily-python is not installed. Run: pip install tavily-python"
            ) from None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """Return the bare hostname (e.g. ``economictimes.indiatimes.com``)."""
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:  # noqa: BLE001
        return ""


def _domain_credibility(domain: str) -> float:
    """Look up a credibility score for *domain*."""
    domain_lower = domain.lower()
    for key, score in _SOURCE_CREDIBILITY.items():
        if key in domain_lower:
            return score
    return _DEFAULT_CREDIBILITY


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    company  = sys.argv[1] if len(sys.argv) > 1 else "Tata Steel"
    promoters = sys.argv[2:]

    print(f"\n{'='*60}")
    print(f"NewsIntelligenceTool — smoke test for: {company}")
    print(f"Promoters: {promoters or '(none)'}")
    print(f"{'='*60}\n")

    tool   = NewsIntelligenceTool()
    report = tool.search_company_news(company, promoters)

    print(f"  Total articles fetched : {report['total_article_count']}")
    print(f"  Negative articles      : {report['negative_article_count']}")
    print(f"  News risk score        : {report['news_risk_score']} / 10")
    print(f"  Source credibility     : {report['source_credibility_score']}")
    print(f"  Risk tag frequency     : {report['risk_tag_frequency']}")

    if report["most_alarming_headline"]:
        h = report["most_alarming_headline"]
        print(f"\n  Most alarming headline:")
        print(f"    {h['title']}")
        print(f"    sentiment={h['sentiment_score']}  tags={h['risk_tags']}")
        print(f"    {h['url']}")

    if report["high_risk_articles"]:
        print(f"\n  High-risk articles ({len(report['high_risk_articles'])}):")
        for art in report["high_risk_articles"][:3]:
            print(f"    [{art['sentiment_score']:+.3f}] {art['title'][:80]}")
            print(f"           tags={art['risk_tags']}  src={art['source_domain']}")

    print(f"\n{'='*60}\n")
