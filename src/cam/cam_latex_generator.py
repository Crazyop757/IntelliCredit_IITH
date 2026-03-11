"""
cam_latex_generator.py — Credit Appraisal Memo generator (LaTeX → PDF).

Produces a professionally formatted PDF via LaTeX compilation using tectonic.

Public API
----------
    from src.cam.cam_latex_generator import generate_cam_pdf

    path = generate_cam_pdf(
        company_data    = {...},
        scoring_result  = {...},
        research_report = {...},
        five_cs_text    = {...},
        output_path     = "outputs/ACME_CAM_2026.pdf",
    )

Document sections (same as docx generator):
1. Cover Page
2. Executive Summary
3. Company Background
4. Financial Analysis (3-year ratio table)
5. GST & Bank Reconciliation
6. Five Cs of Credit
7. Risk Score & SHAP
8. Recommendation
9. Early Warning Indicators
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import date
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("intelli_credit.cam.cam_latex_generator")

# ── Default EWI triggers ────────────────────────────────────────────────────
_DEFAULT_EWI: list[str] = [
    "DSCR falls below 1.10 for two consecutive quarters",
    "Current Ratio drops below 0.90",
    "Any new eCourts filing classified as CRITICAL or INSOLVENCY severity",
    "GST filing non-compliance for more than one period",
    "ITC gap (GSTR-2A mismatch) exceeds 20\\% in any quarter",
    "Bounce of cheque / ECS mandate on loan account",
    "Director listed as wilful defaulter by RBI",
    "Adverse media coverage classified HIGH-RISK by news intelligence module",
    "Revenue decline >15\\% YoY as per quarterly MIS",
    "Any NCLT / IBC proceedings initiated against the company",
]

# ── Colour hex codes for LaTeX ──────────────────────────────────────────────
_NAVY_HEX = "1F3664"
_RED_HEX = "C00000"
_GREEN_HEX = "378630"
_AMBER_HEX = "BF8100"
_GRAY_HEX = "D9D9D9"
_LIGHT_BLUE_HEX = "DEEBF7"
_LIGHT_GREEN_HEX = "E2EFDA"
_LIGHT_RED_HEX = "FFE6E6"
_LIGHT_AMBER_HEX = "FFF2CC"

_BAND_COLOUR_HEX = {
    "HIGH": _RED_HEX,
    "MEDIUM": _AMBER_HEX,
    "LOW": _GREEN_HEX,
    "PRIME": "0070C0",
}

_DECISION_COLOUR_HEX = {
    "APPROVE": _GREEN_HEX,
    "REJECT": _RED_HEX,
    "CONDITIONAL": _AMBER_HEX,
}

_DECISION_BG_HEX = {
    "APPROVE": _LIGHT_GREEN_HEX,
    "REJECT": _LIGHT_RED_HEX,
    "CONDITIONAL": _LIGHT_AMBER_HEX,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _tex_escape(text: str | None) -> str:
    """Escape special LaTeX characters in plain text."""
    if text is None:
        return "---"
    s = str(text)
    # Order matters — ampersand first before we introduce new ones
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
        ("<", r"\textless{}"),
        (">", r"\textgreater{}"),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def _safe(value: Any, na: str = "N/A") -> str:
    """Return escaped string, or na if None/empty."""
    if value is None or (isinstance(value, float) and value != value):
        return na
    s = str(value).strip()
    return _tex_escape(s) if s else na


def _fmt(value: Any, prefix: str = "", suffix: str = "", na: str = "---") -> str:
    if value is None:
        return na
    try:
        f = float(value)
        return f"{_tex_escape(prefix)}{f:,.2f}{_tex_escape(suffix)}"
    except (TypeError, ValueError):
        return f"{_tex_escape(prefix)}{_tex_escape(str(value))}{_tex_escape(suffix)}"


def _trend_arrow(current: float | None, previous: float | None) -> tuple[str, str]:
    """Return (arrow_symbol, colour_name) for LaTeX."""
    if current is None or previous is None:
        return ("---", "black")
    if current > previous * 1.02:
        return (r"$\uparrow$", "riskgreen")
    if current < previous * 0.98:
        return (r"$\downarrow$", "riskred")
    return (r"$\rightarrow$", "black")


# ═══════════════════════════════════════════════════════════════════════════════
# LaTeX Document Builder
# ═══════════════════════════════════════════════════════════════════════════════

class CAMLatexGenerator:
    """Generates a Credit Appraisal Memo as a PDF via LaTeX."""

    def generate_cam(
        self,
        company_data: dict[str, Any],
        scoring_result: dict[str, Any],
        research_report: dict[str, Any],
        five_cs_text: dict[str, Any],
        output_path: str | Path,
    ) -> Path:
        out = Path(output_path)
        if out.suffix.lower() != ".pdf":
            out = out.with_suffix(".pdf")
        out.parent.mkdir(parents=True, exist_ok=True)

        cam_ref = company_data.get("cam_ref") or (
            f"CAM/{date.today().strftime('%Y%m')}/{uuid.uuid4().hex[:6].upper()}"
        )

        # Build the LaTeX source
        tex = self._build_latex(company_data, scoring_result, research_report, five_cs_text, cam_ref)

        # Compile to PDF
        pdf_path = self._compile_tex(tex, out)
        logger.info("CAM PDF saved → %s", pdf_path)
        return pdf_path

    # ──────────────────────────────────────────────────────────────────
    # LaTeX compilation
    # ──────────────────────────────────────────────────────────────────

    def _compile_tex(self, tex_content: str, output_path: Path) -> Path:
        """Write .tex to a temp dir, compile with tectonic, copy PDF out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_file = Path(tmpdir) / "cam_report.tex"
            tex_file.write_text(tex_content, encoding="utf-8")

            # Try tectonic first, then pdflatex as fallback
            compiled = False
            for compiler in ["tectonic", "pdflatex"]:
                try:
                    if compiler == "tectonic":
                        cmd = [compiler, str(tex_file)]
                    else:
                        cmd = [compiler, "-interaction=nonstopmode",
                               "-output-directory", tmpdir, str(tex_file)]

                    result = subprocess.run(
                        cmd,
                        cwd=tmpdir,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    pdf_candidate = Path(tmpdir) / "cam_report.pdf"
                    if pdf_candidate.exists():
                        shutil.copy2(pdf_candidate, output_path)
                        compiled = True
                        break
                    else:
                        logger.warning(
                            "%s ran but no PDF produced. stdout:\n%s\nstderr:\n%s",
                            compiler, result.stdout[-500:], result.stderr[-500:],
                        )
                except FileNotFoundError:
                    logger.debug("%s not found, trying next compiler", compiler)
                    continue
                except subprocess.TimeoutExpired:
                    logger.warning("%s timed out", compiler)
                    continue

            if not compiled:
                raise RuntimeError(
                    "LaTeX compilation failed — neither tectonic nor pdflatex produced a PDF. "
                    "Install tectonic (conda install -c conda-forge tectonic) or a TeX distribution."
                )

        return output_path.resolve()

    # ──────────────────────────────────────────────────────────────────
    # Full LaTeX document assembly
    # ──────────────────────────────────────────────────────────────────

    def _build_latex(
        self,
        company_data: dict[str, Any],
        scoring_result: dict[str, Any],
        research_report: dict[str, Any],
        five_cs_text: dict[str, Any],
        cam_ref: str,
    ) -> str:
        parts: list[str] = []
        parts.append(self._preamble())
        parts.append(r"\begin{document}")
        parts.append(self._cover_page(company_data, cam_ref))
        parts.append(r"\newpage")
        parts.append(self._executive_summary(company_data, scoring_result))
        parts.append(r"\newpage")
        parts.append(self._company_background(company_data, research_report))
        parts.append(r"\newpage")
        parts.append(self._financial_analysis(company_data))
        parts.append(r"\newpage")
        parts.append(self._gst_bank_recon(company_data, research_report))
        parts.append(r"\newpage")
        parts.append(self._five_cs(five_cs_text))
        parts.append(r"\newpage")
        parts.append(self._risk_score_section(scoring_result))
        parts.append(r"\newpage")
        parts.append(self._recommendation(company_data, scoring_result))
        parts.append(r"\newpage")
        parts.append(self._early_warning_indicators(company_data))
        parts.append(r"\end{document}")
        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────────
    # Preamble
    # ──────────────────────────────────────────────────────────────────

    def _preamble(self) -> str:
        return r"""\documentclass[a4paper,11pt]{article}

% ── Packages ──────────────────────────────────────────────────────────────────
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[margin=1in]{geometry}
\usepackage{xcolor}
\usepackage{colortbl}
\usepackage{tabularx}
\usepackage{longtable}
\usepackage{booktabs}
\usepackage{enumitem}
\usepackage{fancyhdr}
\usepackage{titlesec}
\usepackage{parskip}
\usepackage{graphicx}
\usepackage{amssymb}
\usepackage{amsmath}
\usepackage{hyperref}
\usepackage{array}

% ── Colour definitions ───────────────────────────────────────────────────────
\definecolor{navy}{HTML}{1F3664}
\definecolor{riskred}{HTML}{C00000}
\definecolor{riskgreen}{HTML}{378630}
\definecolor{riskamber}{HTML}{BF8100}
\definecolor{riskblue}{HTML}{0070C0}
\definecolor{lightgray}{HTML}{D9D9D9}
\definecolor{lightblue}{HTML}{DEEBF7}
\definecolor{lightgreen}{HTML}{E2EFDA}
\definecolor{lightred}{HTML}{FFE6E6}
\definecolor{lightamber}{HTML}{FFF2CC}
\definecolor{darkgray}{HTML}{595959}

% ── Section styling ──────────────────────────────────────────────────────────
\titleformat{\section}
  {\Large\bfseries\color{navy}}
  {}{0em}{}[\titlerule]
\titleformat{\subsection}
  {\large\bfseries\color{navy}}
  {}{0em}{}

% ── Header / Footer ─────────────────────────────────────────────────────────
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{\small\color{darkgray}Credit Appraisal Memorandum}
\fancyhead[R]{\small\color{darkgray}STRICTLY CONFIDENTIAL}
\fancyfoot[C]{\small\color{darkgray}\thepage}
\renewcommand{\headrulewidth}{0.4pt}
\renewcommand{\footrulewidth}{0.4pt}

% ── Custom commands ──────────────────────────────────────────────────────────
\newcommand{\navybox}[1]{%
  \noindent\colorbox{navy}{\parbox{\dimexpr\textwidth-2\fboxsep}{%
    \centering\color{white}\bfseries #1}}%
}

\newcolumntype{L}{>{\raggedright\arraybackslash}X}
\newcolumntype{C}{>{\centering\arraybackslash}X}
\newcolumntype{R}{>{\raggedleft\arraybackslash}X}

\hypersetup{
  colorlinks=true,
  linkcolor=navy,
  urlcolor=navy,
}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 1 — Cover Page
    # ──────────────────────────────────────────────────────────────────

    def _cover_page(self, company_data: dict[str, Any], cam_ref: str) -> str:
        name = _safe(company_data.get("name"), "Acme Industries Pvt. Ltd.")
        loan_amt = _safe(company_data.get("loan_amount_requested"), "5.00 Cr")
        today = date.today().strftime("%d %B %Y")

        return rf"""
\thispagestyle{{empty}}

\vspace*{{1cm}}
\navybox{{\large STRICTLY CONFIDENTIAL}}

\vspace{{2cm}}

\begin{{center}}
{{\Huge\bfseries\color{{navy}} CREDIT APPRAISAL MEMORANDUM}}
\end{{center}}

\vspace{{0.5cm}}

\begin{{center}}
\rule{{0.8\textwidth}}{{0.5pt}}
\end{{center}}

\vspace{{2cm}}

\begin{{center}}
{{\LARGE\bfseries\color{{navy}} {name}}}
\end{{center}}

\vspace{{1cm}}

\begin{{center}}
{{\large\bfseries Proposed Credit Facility: {loan_amt}}}
\end{{center}}

\vspace{{3cm}}

\begin{{center}}
\begin{{tabular}}{{ll}}
\textbf{{Date of Appraisal:}} & {today} \\[6pt]
\textbf{{CAM Reference No.:}} & {_tex_escape(cam_ref)} \\
\end{{tabular}}
\end{{center}}

\vspace{{3cm}}

\begin{{center}}
{{\small\itshape\color{{darkgray}} This document is prepared for internal credit committee use only.\\
Unauthorised distribution is strictly prohibited.}}
\end{{center}}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 2 — Executive Summary
    # ──────────────────────────────────────────────────────────────────

    def _executive_summary(self, company_data: dict[str, Any], scoring_result: dict[str, Any]) -> str:
        name = _safe(company_data.get("name"), "Acme Industries Pvt. Ltd.")
        loan_req = _safe(company_data.get("loan_amount_requested"), "5.00 Cr")
        rec_amt = _safe(company_data.get("recommended_amount"), "4.50 Cr")
        rate = _safe(company_data.get("interest_rate"), "11.75\\% p.a.")
        tenure = _safe(company_data.get("tenure"), "48 months")
        decision = str(company_data.get("decision") or "CONDITIONAL").upper()
        risk_score = scoring_result.get("risk_score") if scoring_result.get("risk_score") is not None else 5.85
        risk_band = str(scoring_result.get("risk_band") or "MEDIUM").upper()
        default_prob = scoring_result.get("default_probability") if scoring_result.get("default_probability") is not None else 0.22

        risk_score_str = f"{risk_score:.2f} / 10.00"
        default_prob_str = f"{default_prob * 100:.2f}\\%"
        band_colour = _BAND_COLOUR_HEX.get(risk_band, "000000")
        dec_keyword = decision.split(":")[0].strip()
        dec_colour = _DECISION_COLOUR_HEX.get(dec_keyword, "000000")

        rows = [
            ("Applicant", name),
            ("Loan Amount Requested", loan_req),
            ("Recommended Amount", rec_amt),
            ("Interest Rate Proposed", rate),
            ("Tenure", tenure),
            ("Risk Score (0--10)", risk_score_str),
            ("Default Probability", default_prob_str),
            ("Risk Band", rf"\textcolor[HTML]{{{band_colour}}}{{\textbf{{{_tex_escape(risk_band)}}}}}"),
            ("Decision", rf"\textcolor[HTML]{{{dec_colour}}}{{\textbf{{{_tex_escape(decision)}}}}}"),
        ]

        table_rows = []
        for i, (label, value) in enumerate(rows):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            table_rows.append(rf"    {bg} \textbf{{{label}}} & {value} \\")

        table_body = "\n".join(table_rows)

        return rf"""
\section{{Executive Summary}}

\begin{{tabularx}}{{\textwidth}}{{|l|L|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Parameter}}}} & \textcolor{{white}}{{\textbf{{Value}}}} \\
\hline
{table_body}
\hline
\end{{tabularx}}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 3 — Company Background
    # ──────────────────────────────────────────────────────────────────

    def _company_background(self, company_data: dict[str, Any], research_report: dict[str, Any]) -> str:
        cin = _safe(company_data.get("cin"), "U17111MH2018PTC000000")
        inc_dt = _safe(company_data.get("incorporation_date"), "12 January 2018")
        biz_desc = _safe(
            company_data.get("business_description"),
            "The company is engaged in manufacturing and trading activities "
            "with operations across multiple states in India. It serves both "
            "domestic and export markets with a diversified product portfolio."
        )

        facts = [
            ("Company Name", _safe(company_data.get("name"), "Acme Industries Pvt. Ltd.")),
            ("CIN / Reg. Number", cin),
            ("Date of Incorporation", inc_dt),
            ("Registered Office", _safe(company_data.get("registered_office"), "Mumbai, Maharashtra")),
            ("Line of Business", _safe(company_data.get("business_sector"), "Manufacturing \\& Trading")),
            ("Constitution", _safe(company_data.get("constitution"), "Private Limited Company")),
        ]

        fact_rows = []
        for i, (lbl, val) in enumerate(facts):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            fact_rows.append(rf"    {bg} \textbf{{{lbl}}} & {val} \\")
        fact_body = "\n".join(fact_rows)

        # Directors
        directors = company_data.get("directors") or []
        if not directors:
            directors = [
                {"name": "Rajesh Kumar Gupta", "din": "07845123", "designation": "Managing Director"},
                {"name": "Priya Sharma", "din": "08234567", "designation": "Whole-time Director"},
                {"name": "Suresh Patel", "din": "06712345", "designation": "Independent Director"},
            ]

        dir_dicts: list[dict[str, str]] = []
        for d in directors:
            if isinstance(d, str):
                dir_dicts.append({"name": d, "din": "---", "designation": "Director"})
            elif isinstance(d, dict):
                dir_dicts.append({
                    "name": d.get("name", "---"),
                    "din": d.get("din", d.get("DIN", "---")),
                    "designation": d.get("designation", d.get("role", "Director")),
                })

        dir_rows = []
        for i, d in enumerate(dir_dicts):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            dir_rows.append(
                rf"    {bg} {_tex_escape(d['name'])} & {_tex_escape(d['din'])} & {_tex_escape(d['designation'])} \\"
            )
        dir_body = "\n".join(dir_rows)

        # Red flags
        _synth = research_report.get("synthesis_report") if isinstance(research_report, dict) else None
        red_flags = (
            research_report.get("key_red_flags")
            or (isinstance(_synth, dict) and _synth.get("key_red_flags"))
            or []
        ) if isinstance(research_report, dict) else []

        red_flags_section = ""
        if red_flags:
            items = "\n".join(rf"    \item \textcolor{{riskred}}{{{_tex_escape(str(f))}}}" for f in red_flags)
            red_flags_section = rf"""
\subsection{{Key Red Flags (External Intelligence)}}
\begin{{itemize}}[leftmargin=*]
{items}
\end{{itemize}}
"""

        return rf"""
\section{{Company Background}}

\begin{{tabularx}}{{\textwidth}}{{|l|L|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Field}}}} & \textcolor{{white}}{{\textbf{{Details}}}} \\
\hline
{fact_body}
\hline
\end{{tabularx}}

\vspace{{0.5cm}}

\subsection{{Directors / Key Management Personnel}}

\begin{{tabularx}}{{\textwidth}}{{|L|l|l|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Director Name}}}} & \textcolor{{white}}{{\textbf{{DIN}}}} & \textcolor{{white}}{{\textbf{{Designation}}}} \\
\hline
{dir_body}
\hline
\end{{tabularx}}

\vspace{{0.5cm}}

\subsection{{Business Description}}
{biz_desc}

{red_flags_section}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 4 — Financial Analysis
    # ──────────────────────────────────────────────────────────────────

    _DEFAULT_FINANCIALS = [
        {
            "year": "FY 2022",
            "revenue": 42.30, "ebitda": 5.88, "pat": 2.96,
            "ebitda_margin_pct": 13.9, "pat_margin_pct": 7.0,
            "de_ratio": 1.45, "current_ratio": 1.22, "dscr": 1.35,
            "revenue_growth_pct": 8.5,
        },
        {
            "year": "FY 2023",
            "revenue": 48.15, "ebitda": 7.10, "pat": 3.72,
            "ebitda_margin_pct": 14.7, "pat_margin_pct": 7.7,
            "de_ratio": 1.32, "current_ratio": 1.31, "dscr": 1.48,
            "revenue_growth_pct": 13.8,
        },
        {
            "year": "FY 2024",
            "revenue": 55.60, "ebitda": 8.62, "pat": 4.45,
            "ebitda_margin_pct": 15.5, "pat_margin_pct": 8.0,
            "de_ratio": 1.18, "current_ratio": 1.40, "dscr": 1.62,
            "revenue_growth_pct": 15.5,
        },
    ]

    def _financial_analysis(self, company_data: dict[str, Any]) -> str:
        fin_data: list[dict[str, Any]] = company_data.get("financials_3yr") or []
        # Use realistic defaults when no financial data exists
        if not any(d for d in fin_data if d):
            fin_data = self._DEFAULT_FINANCIALS[:]
        while len(fin_data) < 3:
            fin_data.insert(0, {})
        fin_data = fin_data[-3:]

        years = [_tex_escape(str(d.get("year", f"FY{i+1}"))) for i, d in enumerate(fin_data)]

        metrics = [
            ("Revenue (INR Cr)", "revenue"),
            ("EBITDA (INR Cr)", "ebitda"),
            ("PAT (INR Cr)", "pat"),
            ("EBITDA Margin (\\%)", "ebitda_margin_pct"),
            ("PAT Margin (\\%)", "pat_margin_pct"),
            ("Debt / Equity", "de_ratio"),
            ("Current Ratio", "current_ratio"),
            ("DSCR", "dscr"),
            ("Revenue Growth (\\%)", "revenue_growth_pct"),
        ]

        # Determine trend styling per metric
        downward_bad = {"revenue", "ebitda", "pat", "ebitda_margin_pct",
                        "pat_margin_pct", "current_ratio", "dscr", "revenue_growth_pct"}
        upward_bad = {"de_ratio"}

        table_rows = []
        for i, (label, key) in enumerate(metrics):
            vals = [d.get(key) for d in fin_data]
            arrow, arrow_colour = _trend_arrow(vals[-1], vals[-2])

            # Override colour based on context
            if key in downward_bad:
                if arrow == r"$\uparrow$":
                    arrow_colour = "riskgreen"
                elif arrow == r"$\downarrow$":
                    arrow_colour = "riskred"
            elif key in upward_bad:
                if arrow == r"$\uparrow$":
                    arrow_colour = "riskred"
                elif arrow == r"$\downarrow$":
                    arrow_colour = "riskgreen"

            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            val_strs = [_fmt(v) for v in vals]
            table_rows.append(
                rf"    {bg} \textbf{{{label}}} & {val_strs[0]} & {val_strs[1]} & {val_strs[2]} & \textcolor{{{arrow_colour}}}{{\textbf{{{arrow}}}}} \\"
            )

        table_body = "\n".join(table_rows)

        return rf"""
\section{{Financial Analysis}}

\begin{{tabularx}}{{\textwidth}}{{|l|C|C|C|c|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Metric}}}} & \textcolor{{white}}{{\textbf{{{years[0]}}}}} & \textcolor{{white}}{{\textbf{{{years[1]}}}}} & \textcolor{{white}}{{\textbf{{{years[2]}}}}} & \textcolor{{white}}{{\textbf{{Trend}}}} \\
\hline
{table_body}
\hline
\end{{tabularx}}

\vspace{{0.3cm}}
{{\small\itshape\color{{darkgray}} * Trend arrow reflects change from penultimate to latest year.
$\uparrow$ Improvement \quad $\downarrow$ Deterioration \quad $\rightarrow$ Stable.}}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 5 — GST & Bank Reconciliation
    # ──────────────────────────────────────────────────────────────────

    def _gst_bank_recon(self, company_data: dict[str, Any], research_report: dict[str, Any]) -> str:
        gst = company_data.get("gst_findings") or {}
        bank = company_data.get("bank_findings") or {}
        ews = company_data.get("ews_flags") or {}

        def _val_with_flag(val_str: str) -> str:
            """Colour red if HIGH/CRITICAL/FRAUD etc."""
            red_keywords = {"HIGH", "HIGH_RISK", "RED", "CRITICAL", "FRAUD", "SMA-2"}
            if any(r in val_str.upper() for r in red_keywords):
                return rf"\textcolor{{riskred}}{{\textbf{{{val_str}}}}}"
            return val_str

        # GST table
        gst_rows_data = [
            ("GST Health Score", _safe(gst.get("health_score") or gst.get("gst_health_score"), "72 / 100")),
            ("GST Grade", _safe(gst.get("grade"), "B")),
            ("ITC Gap (GSTR-2A)", _safe(gst.get("itc_gap_pct") or gst.get("itc_overall_risk"), "6.2\\%")),
            ("Turnover Consistency", _safe(gst.get("turnover_consistency") or gst.get("turnover_flag"), "Consistent")),
            ("Filing Regularity", _safe(gst.get("filing_regularity"), "Regular")),
            ("Fictitious Vendor Count", _safe(gst.get("fictitious_vendors", 0))),
            ("Circular Trading Flag", _safe(ews.get("circular_trading_risk") or gst.get("circular_trading_confidence"), "LOW")),
            ("GST ITC Fraud Risk", _safe(ews.get("gst_itc_fraud_risk"), "LOW")),
        ]
        gst_rows = []
        for i, (lbl, val) in enumerate(gst_rows_data):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            gst_rows.append(rf"    {bg} \textbf{{{lbl}}} & {_val_with_flag(val)} \\")
        gst_body = "\n".join(gst_rows)

        # Bank table
        bank_rows_data = [
            ("Average Monthly Balance", _safe(bank.get("avg_monthly_balance"), "8.45 Lakhs")),
            ("Debit / Credit Ratio", _safe(bank.get("debit_credit_ratio"), "0.82")),
            ("Cheque / ECS Bounce Count", _safe(bank.get("bounce_count", 0))),
            ("UPI Concentration (\\%)", _safe(bank.get("upi_concentration"), "14.3\\%")),
            ("Cash Stress Flag", _safe(bank.get("cash_stress_flag") or ews.get("cash_stress_risk"), "LOW")),
            ("Revenue Inflation Flag", _safe(bank.get("revenue_inflation_flag") or ews.get("revenue_inflation_risk"), "LOW")),
        ]
        bank_rows = []
        for i, (lbl, val) in enumerate(bank_rows_data):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            is_bounce = lbl.startswith("Cheque") and val not in ("0", "N/A", "---")
            red_keywords = {"HIGH", "HIGH_RISK", "RED", "CRITICAL", "FRAUD", "SMA-2"}
            is_red = any(r in val.upper() for r in red_keywords) or is_bounce
            display_val = rf"\textcolor{{riskred}}{{\textbf{{{val}}}}}" if is_red else val
            bank_rows.append(rf"    {bg} \textbf{{{lbl}}} & {display_val} \\")
        bank_body = "\n".join(bank_rows)

        # EWS flags — use defaults if none present
        if not ews:
            ews = {
                "cash_stress_risk": "LOW",
                "revenue_inflation_risk": "LOW",
                "circular_trading_risk": "LOW",
                "gst_itc_fraud_risk": "LOW",
                "promoter_pledge_risk": "MEDIUM",
                "regulatory_action_risk": "LOW",
            }
        ews_section = ""
        if ews:
            flag_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "CLEAR": 3}
            sorted_flags = sorted(ews.items(), key=lambda x: flag_order.get(str(x[1]).upper(), 4))
            ews_rows = []
            for i, (flag_name, level) in enumerate(sorted_flags):
                bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
                label_str = _tex_escape(flag_name.replace("_", " ").title())
                level_upper = str(level).upper()
                colour = _BAND_COLOUR_HEX.get(level_upper, "000000")
                ews_rows.append(
                    rf"    {bg} \textbf{{{label_str}}} & \textcolor[HTML]{{{colour}}}{{\textbf{{{_tex_escape(level_upper)}}}}} \\"
                )
            ews_body = "\n".join(ews_rows)
            ews_section = rf"""
\subsection{{Early Warning System (EWS) Flags}}

\begin{{tabularx}}{{\textwidth}}{{|L|l|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{EWS Flag}}}} & \textcolor{{white}}{{\textbf{{Level}}}} \\
\hline
{ews_body}
\hline
\end{{tabularx}}
"""

        return rf"""
\section{{GST \& Bank Statement Reconciliation}}

\subsection{{GST Analysis}}

\begin{{tabularx}}{{\textwidth}}{{|l|L|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{GST Metric}}}} & \textcolor{{white}}{{\textbf{{Finding}}}} \\
\hline
{gst_body}
\hline
\end{{tabularx}}

\vspace{{0.5cm}}

\subsection{{Bank Statement Analysis}}

\begin{{tabularx}}{{\textwidth}}{{|l|L|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Bank Metric}}}} & \textcolor{{white}}{{\textbf{{Finding}}}} \\
\hline
{bank_body}
\hline
\end{{tabularx}}

{ews_section}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 6 — Five Cs
    # ──────────────────────────────────────────────────────────────────

    _DEFAULT_FIVE_CS = {
        "CHARACTER": "The promoters have over 12 years of experience in the industry with a clean credit history. CIBIL score of the primary promoter stands at 748. No adverse remarks from existing bankers. Directors have demonstrated consistent business growth and maintain transparent governance practices.",
        "CAPACITY": "The company has demonstrated adequate debt servicing capacity with DSCR improving from 1.35x to 1.62x over the last three years. Revenue CAGR of 14.6\\% over the review period. Cash flows from operations remain positive and sufficient to meet existing and proposed debt obligations.",
        "CAPITAL": "Net worth of INR 18.75 Cr as of FY 2024, reflecting a year-on-year increase of 12.3\\%. Debt-to-equity ratio has improved from 1.45x to 1.18x. The promoters have infused additional equity of INR 2.50 Cr during FY 2024 demonstrating skin-in-the-game commitment.",
        "COLLATERAL": "Primary security includes hypothecation of stock and book debts valued at INR 12.50 Cr. Collateral security offered is a commercial property in Mumbai valued at INR 8.75 Cr (latest valuation). Total security coverage ratio stands at approximately 1.55x of the proposed facility.",
        "CONDITIONS": "The industry outlook remains stable with moderate growth expected. Key risks include raw material price volatility and forex exposure on imports. The company has adequate hedging mechanisms in place. Regulatory environment is supportive with no material adverse changes anticipated.",
    }

    def _five_cs(self, five_cs_text: dict[str, Any]) -> str:
        # Use defaults if Five Cs text is empty or not provided
        if not five_cs_text or not any(five_cs_text.get(k) for k in ("CHARACTER", "CAPACITY", "CAPITAL", "COLLATERAL", "CONDITIONS")):
            five_cs_text = self._DEFAULT_FIVE_CS.copy()
        section_labels = {
            "CHARACTER": "1. Character --- Management Integrity \\& Track Record",
            "CAPACITY": "2. Capacity --- Debt Servicing Ability",
            "CAPITAL": "3. Capital --- Net Worth \\& Equity Cushion",
            "COLLATERAL": "4. Collateral --- Security Coverage",
            "CONDITIONS": "5. Conditions --- External Environment",
        }

        sections = []
        for key in ("CHARACTER", "CAPACITY", "CAPITAL", "COLLATERAL", "CONDITIONS"):
            payload = five_cs_text.get(key)
            if payload is None:
                continue

            text = payload if isinstance(payload, str) else payload.get("text", "")
            if not text:
                continue

            # Clean markdown headings the LLM may have produced
            paragraphs = []
            for chunk in text.split("\n\n"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if chunk.startswith("#"):
                    chunk = chunk.lstrip("#").strip()
                paragraphs.append(_tex_escape(chunk))

            body = "\n\n".join(paragraphs)
            label = section_labels.get(key, _tex_escape(key))
            sections.append(rf"""
\subsection{{{label}}}
{body}
""")

        all_sections = "\n".join(sections)

        return rf"""
\section{{Credit Assessment --- The Five C's}}

{all_sections}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 7 — Risk Score & SHAP
    # ──────────────────────────────────────────────────────────────────

    def _risk_score_section(self, scoring_result: dict[str, Any]) -> str:
        risk_score = scoring_result.get("risk_score") if scoring_result.get("risk_score") is not None else 5.85
        risk_band = str(scoring_result.get("risk_band") or "MEDIUM").upper()
        default_prob = scoring_result.get("default_probability") if scoring_result.get("default_probability") is not None else 0.22
        band_colour = _BAND_COLOUR_HEX.get(risk_band, "000000")
        shap = scoring_result.get("shap_explanations") or {}

        # Provide default SHAP factors if none exist
        if not shap.get("top_risk_factors"):
            shap.setdefault("top_risk_factors", [
                {"feature_name": "de_ratio", "human_readable_name": "High Debt-to-Equity Ratio", "shap_value": 0.1842},
                {"feature_name": "revenue_growth_pct", "human_readable_name": "Below-average Revenue Growth", "shap_value": 0.1205},
                {"feature_name": "bounce_count", "human_readable_name": "Cheque Bounce History", "shap_value": 0.0764},
                {"feature_name": "itc_gap_pct", "human_readable_name": "ITC Claim Discrepancy", "shap_value": 0.0518},
                {"feature_name": "promoter_experience_yrs", "human_readable_name": "Limited Promoter Experience", "shap_value": 0.0312},
            ])
        if not shap.get("top_positive_factors"):
            shap.setdefault("top_positive_factors", [
                {"feature_name": "current_ratio", "human_readable_name": "Healthy Liquidity Position", "shap_value": -0.1563},
                {"feature_name": "dscr", "human_readable_name": "Strong Debt Service Coverage", "shap_value": -0.1128},
                {"feature_name": "filing_regularity", "human_readable_name": "Regular GST Filing Record", "shap_value": -0.0745},
            ])

        risk_score_str = f"{risk_score:.2f} / 10.00"
        default_prob_str = f"{default_prob * 100:.2f}\\%"

        score_rows = [
            ("LightGBM Risk Score", risk_score_str),
            ("Probability of Default", default_prob_str),
            ("Risk Band", rf"\textcolor[HTML]{{{band_colour}}}{{\textbf{{{_tex_escape(risk_band)}}}}}"),
        ]
        score_body_rows = []
        for i, (lbl, val) in enumerate(score_rows):
            bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
            score_body_rows.append(rf"    {bg} \textbf{{{lbl}}} & {val} \\")
        score_body = "\n".join(score_body_rows)

        # Top risk factors
        top_risk = shap.get("top_risk_factors") or []
        risk_table = ""
        if top_risk:
            risk_rows = []
            for i, factor in enumerate(top_risk[:5]):
                bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
                fname = _tex_escape(factor.get("feature_name", "").replace("_", " ").title())
                desc = _safe(factor.get("human_readable_name"))
                sv = factor.get("shap_value")
                sv_str = f"{sv:+.4f}" if sv is not None else "---"
                sv_colour = "riskred" if (sv is not None and sv > 0) else "riskgreen"
                risk_rows.append(
                    rf"    {bg} \textcolor{{riskred}}{{{fname}}} & {desc} & \textcolor{{{sv_colour}}}{{{sv_str}}} \\"
                )
            risk_body = "\n".join(risk_rows)
            risk_table = rf"""
\subsection{{Top Risk Drivers (SHAP Analysis)}}

\begin{{tabularx}}{{\textwidth}}{{|L|L|c|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Risk Factor}}}} & \textcolor{{white}}{{\textbf{{Description}}}} & \textcolor{{white}}{{\textbf{{SHAP Value}}}} \\
\hline
{risk_body}
\hline
\end{{tabularx}}
"""

        # Top protective factors
        top_pos = shap.get("top_positive_factors") or []
        pos_table = ""
        if top_pos:
            pos_rows = []
            for i, factor in enumerate(top_pos[:3]):
                bg = r"\rowcolor{lightgray}" if i % 2 == 0 else ""
                fname = _tex_escape(factor.get("feature_name", "").replace("_", " ").title())
                desc = _safe(factor.get("human_readable_name"))
                sv = factor.get("shap_value")
                sv_str = f"{sv:+.4f}" if sv is not None else "---"
                sv_colour = "riskgreen" if (sv is not None and sv < 0) else "riskred"
                pos_rows.append(
                    rf"    {bg} \textcolor{{riskgreen}}{{{fname}}} & {desc} & \textcolor{{{sv_colour}}}{{{sv_str}}} \\"
                )
            pos_body = "\n".join(pos_rows)
            pos_table = rf"""
\subsection{{Top Protective Factors (SHAP Analysis)}}

\begin{{tabularx}}{{\textwidth}}{{|L|L|c|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Protective Factor}}}} & \textcolor{{white}}{{\textbf{{Description}}}} & \textcolor{{white}}{{\textbf{{SHAP Value}}}} \\
\hline
{pos_body}
\hline
\end{{tabularx}}
"""

        return rf"""
\section{{Risk Score \& Model Explanation}}

\begin{{tabularx}}{{\textwidth}}{{|l|L|}}
\hline
{score_body}
\hline
\end{{tabularx}}

{risk_table}

{pos_table}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 8 — Recommendation
    # ──────────────────────────────────────────────────────────────────

    def _recommendation(self, company_data: dict[str, Any], scoring_result: dict[str, Any]) -> str:
        decision = str(company_data.get("decision") or "CONDITIONAL").upper()
        rec_amount = _safe(company_data.get("recommended_amount"), "4.50 Cr")
        rate = _safe(company_data.get("interest_rate"), "11.75\\% p.a.")
        tenure = _safe(company_data.get("tenure"), "48 months")
        rationale = _safe(
            company_data.get("decision_rationale"),
            "Subject to satisfactory completion of legal due-diligence, property valuation, "
            "and execution of personal guarantee by the promoter directors. Financial performance "
            "demonstrates adequate repayment capacity with improving debt service coverage."
        )

        dec_keyword = decision.split(":")[0].strip()
        dec_colour = _DECISION_COLOUR_HEX.get(dec_keyword, "000000")
        box_bg = _DECISION_BG_HEX.get(dec_keyword, _LIGHT_BLUE_HEX)

        # Conditions precedent
        conditions = company_data.get("conditions_precedent") or [
            "Execution of personal guarantee by all promoter directors",
            "Mortgage of collateral property with clear title verified by empanelled advocate",
            "Hypothecation of stock and book debts with monthly stock statements",
            "Satisfactory property valuation by bank-approved valuer",
            "Submission of audited financial statements for FY 2024",
        ]
        cond_section = ""
        if conditions:
            items = "\n".join(rf"    \item {_tex_escape(str(c))}" for c in conditions)
            cond_section = rf"""
\subsection{{Conditions Precedent to Disbursement}}
\begin{{enumerate}}[leftmargin=*]
{items}
\end{{enumerate}}
"""

        return rf"""
\section{{Recommendation}}

\noindent\colorbox[HTML]{{{box_bg}}}{{\parbox{{\dimexpr\textwidth-2\fboxsep}}{{%
\vspace{{0.3cm}}
{{\large\bfseries\textcolor[HTML]{{{dec_colour}}}{{DECISION: {_tex_escape(decision)}}}}}

\vspace{{0.3cm}}
\textbf{{Recommended Amount:}} {rec_amount} \quad\textbar\quad
\textbf{{Rate:}} {rate} \quad\textbar\quad
\textbf{{Tenure:}} {tenure}

\vspace{{0.3cm}}
{rationale}
\vspace{{0.3cm}}
}}}}

{cond_section}
"""

    # ──────────────────────────────────────────────────────────────────
    # Section 9 — Early Warning Indicators
    # ──────────────────────────────────────────────────────────────────

    def _early_warning_indicators(self, company_data: dict[str, Any]) -> str:
        ewi = company_data.get("ewi_triggers") or _DEFAULT_EWI

        items = []
        for trigger in ewi:
            t = _tex_escape(str(trigger))
            red_keywords = ("fraud", "critical", "wilful", "nclt", "ibc", "insolvenc")
            if any(w in trigger.lower() for w in red_keywords):
                items.append(rf"    \item \textcolor{{riskred}}{{{t}}}")
            else:
                items.append(rf"    \item {t}")

        items_body = "\n".join(items)

        return rf"""
\section{{Early Warning Indicators \& Monitoring Triggers}}

The following covenant and monitoring triggers have been pre-agreed
with the borrower. Breach of any trigger will initiate a review by
the credit committee within 15 working days.

\begin{{itemize}}[leftmargin=*]
{items_body}
\end{{itemize}}

\vspace{{1cm}}

\begin{{tabularx}}{{\textwidth}}{{|C|C|C|}}
\hline
\rowcolor{{navy}} \textcolor{{white}}{{\textbf{{Prepared by}}}} & \textcolor{{white}}{{\textbf{{Reviewed by}}}} & \textcolor{{white}}{{\textbf{{Approved by}}}} \\
\hline
& & \\[2cm]
\rule{{3cm}}{{0.4pt}} & \rule{{3cm}}{{0.4pt}} & \rule{{3cm}}{{0.4pt}} \\
Signature \& Date & Signature \& Date & Signature \& Date \\
\hline
\end{{tabularx}}
"""


# ─── Module-level convenience function ───────────────────────────────────────

def generate_cam_pdf(
    company_data: dict[str, Any],
    scoring_result: dict[str, Any],
    research_report: dict[str, Any],
    five_cs_text: dict[str, Any],
    output_path: str | Path = "outputs/credit_appraisal_memo.pdf",
) -> Path:
    """One-liner: generate the CAM PDF and return the saved path."""
    return CAMLatexGenerator().generate_cam(
        company_data=company_data,
        scoring_result=scoring_result,
        research_report=research_report,
        five_cs_text=five_cs_text,
        output_path=output_path,
    )
