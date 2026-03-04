"""
pdf_parser.py — Robust PDF ingestion for intelli_credit.

Handles both digital (native) and scanned PDFs, classifies document type,
and returns a structured extraction result.

Dependencies
------------
    pip install pdfplumber pdf2image Pillow opencv-python-headless pytesseract

Tesseract binary must be installed separately:
    Ubuntu/WSL : sudo apt install tesseract-ocr tesseract-ocr-hin
    Windows    : https://github.com/UB-Mannheim/tesseract/wiki
    macOS      : brew install tesseract tesseract-lang
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("intelli_credit.ingestor.pdf_parser")

# ---------------------------------------------------------------------------
# Document-type taxonomy
# ---------------------------------------------------------------------------

DOC_TYPE_ANNUAL_REPORT    = "ANNUAL_REPORT"
DOC_TYPE_BANK_STATEMENT   = "BANK_STATEMENT"
DOC_TYPE_GST_CERTIFICATE  = "GST_CERTIFICATE"
DOC_TYPE_LEGAL_NOTICE     = "LEGAL_NOTICE"
DOC_TYPE_SANCTION_LETTER  = "SANCTION_LETTER"
DOC_TYPE_UNKNOWN          = "UNKNOWN"

# Keyword lists used for classification (all lowercase).
# More specific / rarer keywords are listed first so they score higher.
_CLASSIFICATION_KEYWORDS: dict[str, list[str]] = {
    DOC_TYPE_ANNUAL_REPORT: [
        "annual report", "board of directors", "director's report",
        "auditor's report", "balance sheet", "profit and loss",
        "statement of profit", "notes to accounts", "standalone financial",
        "consolidated financial", "chairman's message", "corporate governance",
        "earnings per share", "dividend", "agm", "shareholders",
        "annual csr report", "csr report", "sustainability report",
        "integrated report", "corporate social responsibility",
    ],
    DOC_TYPE_BANK_STATEMENT: [
        "bank statement", "account statement", "transaction details",
        "closing balance", "opening balance", "debit", "credit",
        "ifsc", "account number", "branch", "passbook",
        "neft", "rtgs", "imps", "upi",
    ],
    DOC_TYPE_GST_CERTIFICATE: [
        "goods and services tax", "gst", "gstin", "gst certificate",
        "registration certificate", "central tax", "state tax",
        "integrated tax", "cess", "taxpayer", "registration number",
        "place of business",
    ],
    DOC_TYPE_LEGAL_NOTICE: [
        "legal notice", "notice under", "advocate", "counsel",
        "without prejudice", "demand notice", "recovery",
        "arbitration", "court", "plaintiff", "defendant",
        "hereby call upon", "suit filed", "legal proceedings",
    ],
    DOC_TYPE_SANCTION_LETTER: [
        "sanction letter", "sanctioned amount", "loan sanction",
        "working capital", "term loan", "credit facility",
        "rate of interest", "collateral", "moratorium",
        "disbursement", "repayment schedule", "sanctioned limit",
        "lender", "borrower", "processing fee",
    ],
}

# Minimum number of keyword hits to accept a classification
_MIN_KEYWORD_SCORE = 2


# ---------------------------------------------------------------------------
# Internal helpers — image preprocessing
# ---------------------------------------------------------------------------

def _to_grayscale(img_array):
    """Convert a BGR/RGB numpy array to grayscale."""
    import cv2  # noqa: PLC0415
    if len(img_array.shape) == 3:
        return cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
    return img_array


def _adaptive_threshold(gray):
    """Apply adaptive Gaussian threshold to binarise the image."""
    import cv2  # noqa: PLC0415
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10,
    )


def _deskew(gray):
    """
    Detect skew angle via Hough line transform and rotate to correct it.

    Returns the deskewed grayscale image.
    """
    import cv2     # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=80,
        minLineLength=50,
        maxLineGap=10,
    )
    if lines is None:
        return gray

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 != x1:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Only consider near-horizontal lines (±45°)
            if -45 < angle < 45:
                angles.append(angle)

    if not angles:
        return gray

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:  # negligible skew
        return gray

    h, w = gray.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    deskewed = cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    logger.debug("Deskewed by %.2f degrees.", median_angle)
    return deskewed


def _preprocess_for_ocr(pil_image):
    """
    Full preprocessing pipeline for a single PIL image page.

    Steps: convert to numpy → grayscale → deskew → adaptive threshold.
    Returns a PIL image ready for pytesseract.
    """
    import numpy as np  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    img_array = np.array(pil_image.convert("RGB"))
    gray      = _to_grayscale(img_array)
    deskewed  = _deskew(gray)
    binarised = _adaptive_threshold(deskewed)
    return Image.fromarray(binarised)


# ---------------------------------------------------------------------------
# Internal helpers — company name guessing
# ---------------------------------------------------------------------------

_COMPANY_SUFFIXES = re.compile(
    r"\b([A-Z][A-Za-z0-9&\.\s]{2,60}"
    r"(?:Limited|Ltd\.?|Pvt\.? Ltd\.?|Private Limited|LLP|Inc\.?|Corp\.?|"
    r"Corporation|Enterprises|Industries|Holdings|Group|Solutions|Services))"
    r"\b"
)


def _guess_company_name(text: str) -> str | None:
    """
    Heuristically extract the most likely company name from the first 2 000
    characters of *text*.
    """
    snippet = text[:2000]
    matches = _COMPANY_SUFFIXES.findall(snippet)
    if matches:
        # Return the first (usually most prominent) match, normalised.
        return re.sub(r"\s{2,}", " ", matches[0].strip())
    return None


# ---------------------------------------------------------------------------
# Internal helpers — table extraction (pdfplumber)
# ---------------------------------------------------------------------------

def _extract_tables_from_page(page) -> list[dict[str, Any]]:
    """
    Extract all tables from a pdfplumber page object.

    Returns a list of table dicts: {table_id, headers, rows}.
    """
    result: list[dict[str, Any]] = []
    raw_tables = page.extract_tables()
    if not raw_tables:
        return result

    for raw in raw_tables:
        if not raw:
            continue

        # Treat the first row as headers if all cells are non-empty strings;
        # otherwise auto-generate column names.
        first_row = [str(c).strip() if c else "" for c in raw[0]]
        has_headers = all(cell for cell in first_row)
        if has_headers:
            headers = first_row
            data_rows = raw[1:]
        else:
            headers = [f"col_{i}" for i in range(len(first_row))]
            data_rows = raw

        rows: list[dict[str, Any]] = []
        for raw_row in data_rows:
            row_dict: dict[str, Any] = {}
            for col_idx, cell in enumerate(raw_row):
                col_name = headers[col_idx] if col_idx < len(headers) else f"col_{col_idx}"
                row_dict[col_name] = str(cell).strip() if cell is not None else ""
            rows.append(row_dict)

        result.append({
            "table_id": str(uuid.uuid4()),
            "headers":  headers,
            "rows":     rows,
        })

    return result


# ---------------------------------------------------------------------------
# Internal helpers — document classification
# ---------------------------------------------------------------------------

def _classify_document(text: str) -> str:
    """
    Classify document type by counting keyword hits in *text* (case-insensitive).

    Returns the best matching DOC_TYPE_* constant, or DOC_TYPE_UNKNOWN.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for doc_type, keywords in _CLASSIFICATION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score >= _MIN_KEYWORD_SCORE:
            scores[doc_type] = score

    if not scores:
        return DOC_TYPE_UNKNOWN

    return max(scores, key=lambda k: scores[k])


# ---------------------------------------------------------------------------
# Main extraction result
# ---------------------------------------------------------------------------

@dataclass
class ExtractionResult:
    """Structured output returned by :class:`PDFParser`."""

    doc_type:           str
    company_name_guess: str | None
    pages_processed:    int
    raw_text:           str
    tables:             list[dict[str, Any]] = field(default_factory=list)
    metadata:           dict[str, Any]       = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_type":           self.doc_type,
            "company_name_guess": self.company_name_guess,
            "pages_processed":    self.pages_processed,
            "raw_text":           self.raw_text,
            "tables":             self.tables,
            "metadata":           self.metadata,
        }


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------

class PDFParser:
    """
    Auto-detecting PDF parser for digital and scanned documents.

    Parameters
    ----------
    ocr_lang : str
        Tesseract language string.  Default ``"eng+hin"`` supports English
        and Hindi (requires ``tesseract-ocr-hin`` to be installed).
    digital_char_threshold : int
        Minimum characters extracted by pdfplumber before a page is considered
        digital. Pages below this threshold trigger OCR. Default 100.
    dpi : int
        Resolution used when converting scanned pages to images. Default 300.
    max_pages : int | None
        Cap the number of pages parsed (useful for testing). Default None.
    """

    def __init__(
        self,
        ocr_lang:                str       = "eng+hin",
        digital_char_threshold:  int       = 100,
        dpi:                     int       = 300,
        max_pages:               int | None = None,
    ) -> None:
        self.ocr_lang               = ocr_lang
        self.digital_char_threshold = digital_char_threshold
        self.dpi                    = dpi
        self.max_pages              = max_pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, pdf_path: str | Path) -> dict[str, Any]:
        """
        Parse *pdf_path* and return a structured extraction dict.

        The returned dict has the following top-level keys:

        * ``doc_type``           — classified document type
        * ``company_name_guess`` — heuristic company name, or ``None``
        * ``pages_processed``    — number of pages actually parsed
        * ``raw_text``           — full concatenated text
        * ``tables``             — list of ``{table_id, headers, rows}``
        * ``metadata``           — ``{page_count, is_scanned,
                                       extraction_confidence, pdf_path}``

        Raises
        ------
        ValueError
            If the PDF is password-protected and no password is provided.
        FileNotFoundError
            If *pdf_path* does not exist.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        logger.info("Parsing PDF: %s", pdf_path.name)
        return self._parse_internal(pdf_path)

    # ------------------------------------------------------------------
    # Internal orchestration
    # ------------------------------------------------------------------

    def _parse_internal(self, pdf_path: Path) -> dict[str, Any]:
        try:
            import pdfplumber  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "pdfplumber is required: pip install pdfplumber"
            ) from exc

        try:
            pdf = pdfplumber.open(str(pdf_path))
        except Exception as exc:
            exc_str = str(exc).lower()
            if "password" in exc_str or "encrypted" in exc_str:
                raise ValueError(
                    f"PDF is password-protected and cannot be opened: {pdf_path.name}"
                ) from exc
            raise

        with pdf:
            total_pages   = len(pdf.pages)
            pages_to_parse = (
                pdf.pages[: self.max_pages] if self.max_pages else pdf.pages
            )

            all_text_parts: list[str] = []
            all_tables:     list[dict[str, Any]] = []
            scanned_pages   = 0
            digital_pages   = 0
            char_counts:    list[int] = []

            for page_num, page in enumerate(pages_to_parse, start=1):
                logger.debug("  Processing page %d / %d …", page_num, total_pages)

                # --- Try digital extraction first ---
                digital_text = self._extract_digital_text(page)

                if len(digital_text) >= self.digital_char_threshold:
                    # Digital page
                    digital_pages += 1
                    page_text = digital_text
                    page_tables = _extract_tables_from_page(page)
                    all_tables.extend(page_tables)
                    char_counts.append(len(page_text))
                else:
                    # Scanned page — fall back to OCR
                    scanned_pages += 1
                    page_text = self._ocr_page(page, page_num)
                    char_counts.append(len(page_text))

                all_text_parts.append(f"[PAGE {page_num}]\n{page_text}")

        raw_text   = "\n\n".join(all_text_parts)
        is_scanned = scanned_pages > digital_pages  # majority wins

        # Confidence: average chars per page normalised to [0, 1] (cap 1 000)
        avg_chars  = sum(char_counts) / max(len(char_counts), 1)
        confidence = round(min(avg_chars / 1000, 1.0), 3)

        doc_type           = _classify_document(raw_text)
        company_name_guess = _guess_company_name(raw_text)

        pages_processed = len(pages_to_parse)
        logger.info(
            "Done — %d pages | digital=%d scanned=%d | doc_type=%s | confidence=%.3f",
            pages_processed, digital_pages, scanned_pages, doc_type, confidence,
        )

        result = ExtractionResult(
            doc_type           = doc_type,
            company_name_guess = company_name_guess,
            pages_processed    = pages_processed,
            raw_text           = raw_text,
            tables             = all_tables,
            metadata           = {
                "page_count":            total_pages,
                "is_scanned":            is_scanned,
                "digital_pages":         digital_pages,
                "scanned_pages":         scanned_pages,
                "extraction_confidence": confidence,
                "pdf_path":              str(pdf_path),
                "ocr_lang":              self.ocr_lang if is_scanned else None,
            },
        )
        return result.to_dict()

    # ------------------------------------------------------------------
    # Digital extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_digital_text(page) -> str:
        """Extract text from a pdfplumber page, returning empty string on failure."""
        try:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            return (text or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("pdfplumber text extraction error: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # OCR extraction
    # ------------------------------------------------------------------

    def _ocr_page(self, page, page_num: int) -> str:
        """
        Render a pdfplumber page to an image, preprocess, and run Tesseract.

        Falls back to an empty string if any dependency is missing.
        """
        try:
            import pytesseract   # noqa: PLC0415
            from pdf2image import convert_from_bytes  # noqa: PLC0415
        except ImportError as exc:
            logger.warning(
                "OCR dependencies missing (%s). "
                "Install: pip install pdf2image pytesseract",
                exc,
            )
            return ""

        try:
            # Re-render the single page to an image via pdf2image.
            # We use page.pdf.stream to get only the bytes for this page.
            page_pdf_bytes = _extract_single_page_bytes(page)
            images = convert_from_bytes(
                page_pdf_bytes,
                dpi=self.dpi,
                first_page=1,
                last_page=1,
            )
            if not images:
                return ""

            pil_img     = images[0]
            processed   = _preprocess_for_ocr(pil_img)
            ocr_text    = pytesseract.image_to_string(
                processed,
                lang=self.ocr_lang,
                config="--psm 6",   # Assume a single uniform block of text
            )
            return ocr_text.strip()

        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR failed on page %d: %s", page_num, exc)
            return ""


# ---------------------------------------------------------------------------
# Helper — extract single page as PDF bytes (for pdf2image)
# ---------------------------------------------------------------------------

def _extract_single_page_bytes(page) -> bytes:
    """
    Re-serialise a single pdfplumber page into raw PDF bytes.

    Uses pdfplumber's underlying pdfminer page object to build a minimal
    single-page PDF in memory.
    """
    try:
        # pdfplumber >= 0.7 wraps pypdf / pdfminer
        import pikepdf  # noqa: PLC0415

        src:  pikepdf.Pdf = page.pdf._obj  # pdfplumber internal
        out   = pikepdf.Pdf.new()
        out.pages.append(src.pages[page.page_number - 1])
        buf = io.BytesIO()
        out.save(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        pass

    try:
        # Fallback: use pypdf
        from pypdf import PdfReader, PdfWriter  # noqa: PLC0415

        reader  = PdfReader(page.pdf.stream)
        writer  = PdfWriter()
        writer.add_page(reader.pages[page.page_number - 1])
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        pass

    # Last resort: return the entire PDF bytes (pdf2image will still render
    # the requested page via first_page/last_page parameters).
    try:
        page.pdf.stream.seek(0)
        return page.pdf.stream.read()
    except Exception:  # noqa: BLE001
        return b""


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def parse_pdf(
    pdf_path: str | Path,
    ocr_lang: str = "eng+hin",
    max_pages: int | None = None,
) -> dict[str, Any]:
    """
    One-shot helper: create a :class:`PDFParser` and parse *pdf_path*.

    Parameters
    ----------
    pdf_path : str or Path
        Path to the PDF file.
    ocr_lang : str
        Tesseract language string (default ``"eng+hin"``).
    max_pages : int or None
        Cap page count (useful for quick tests).

    Returns
    -------
    dict
        Structured extraction result (see :meth:`PDFParser.parse`).
    """
    parser = PDFParser(ocr_lang=ocr_lang, max_pages=max_pages)
    return parser.parse(pdf_path)


# ---------------------------------------------------------------------------
# Smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <path_to_pdf> [max_pages]")
        sys.exit(1)

    path      = sys.argv[1]
    max_p     = int(sys.argv[2]) if len(sys.argv) > 2 else None
    result    = parse_pdf(path, max_pages=max_p)

    # Print summary (omit full raw_text to keep output readable)
    summary = {k: v for k, v in result.items() if k != "raw_text"}
    summary["raw_text_preview"] = result["raw_text"][:500] + (
        "…" if len(result["raw_text"]) > 500 else ""
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
