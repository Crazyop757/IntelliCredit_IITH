"""
CAM generation service.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from src.api.config import settings

log = logging.getLogger(__name__)


def generate_cam(
    company_data: dict[str, Any],
    scoring_result: dict[str, Any],
    research_report: dict[str, Any],
    five_cs_text: dict[str, Any],
    output_path: Path | None = None,
) -> Path:
    """
    Generate a CAM Word document and return the output path.
    """
    from src.cam.cam_generator import CAMGenerator

    if output_path is None:
        safe_name = (company_data.get("name") or "company").replace(" ", "_")[:30]
        uid = uuid.uuid4().hex[:8]
        output_path = settings.outputs_dir / f"CAM_{safe_name}_{uid}.docx"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    gen = CAMGenerator()
    result_path = gen.generate_cam(
        company_data=company_data,
        scoring_result=scoring_result,
        research_report=research_report,
        five_cs_text=five_cs_text,
        output_path=output_path,
    )
    return Path(result_path)


def generate_five_cs(
    company_data: dict[str, Any],
    financials: dict[str, Any] | None = None,
    research_report: dict[str, Any] | None = None,
    scoring_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate Five C's narrative via LLM writer, falling back to rule-based.
    """
    try:
        from src.cam.five_cs_writer import FiveCsWriter
        writer = FiveCsWriter()

        directors = company_data.get("directors", [])
        character = writer.write_character(company_data, research_report or {})
        capacity = writer.write_capacity(financials or {})
        capital = writer.write_capital(financials or {})
        collateral = writer.write_collateral(
            site_visit={},
            mca_charges=(research_report or {}).get("mca_report", {}),
        )
        conditions = writer.write_conditions(
            research_report=research_report or {},
            sector_data={},
        )

        return {
            "CHARACTER": character,
            "CAPACITY": capacity,
            "CAPITAL": capital,
            "COLLATERAL": collateral,
            "CONDITIONS": conditions,
        }
    except Exception as exc:
        log.warning("LLM Five C's failed, using rule-based fallback: %s", exc)
        return _rule_based_five_cs(company_data, financials or {}, scoring_result or {})


def _rule_based_five_cs(
    company_data: dict,
    financials: dict,
    scoring: dict,
) -> dict[str, Any]:
    name = company_data.get("name", "the company")
    risk_band = scoring.get("risk_band", "MEDIUM")
    dscr = (financials.get("ratios") or {}).get("dscr") or 1.0
    bounce = (company_data.get("bank_findings") or {}).get("bounce_count", 0)
    gst_grade = (company_data.get("gst_findings") or {}).get("grade", "B")
    directors = company_data.get("directors", [])
    dir_names = ", ".join(d.get("name", "") for d in directors[:3]) if directors else "the promoters"

    def _section(key, text):
        wc = len(text.split())
        return {"section": key, "text": text, "word_count": wc, "meets_min_length": wc >= 100}

    char_text = (
        f"{name} is promoted by {dir_names}. "
        f"The company has GST compliance grade {gst_grade}, indicating {'good' if gst_grade in ('A','B') else 'suboptimal'} "
        f"tax discipline. Bank behaviour shows {bounce} cheque/NACH bounce(s). "
        f"Overall character assessment is {'satisfactory' if bounce < 3 else 'requires monitoring'}."
    )

    cap_text = (
        f"{name} demonstrates a DSCR of {dscr:.2f}x, "
        f"reflecting {'adequate' if dscr >= 1.25 else 'tight'} debt service capacity. "
        f"The risk band is {risk_band}, indicating "
        f"{'strong' if risk_band in ('PRIME','LOW') else 'moderate to weak'} repayment capacity."
    )

    cap_text2 = (
        f"The capital structure of {name} is characterised by "
        f"{'conservative' if risk_band in ('PRIME','LOW') else 'elevated'} leverage. "
        f"Net worth adequacy is {'sufficient' if risk_band != 'HIGH' else 'under pressure'}."
    )

    coll_text = (
        f"Collateral to be offered by {name} comprises primary security over assets as per "
        f"standard banking practice, with personal guarantee by {dir_names}. "
        f"Valuation and title clearance to be obtained prior to disbursement."
    )

    cond_text = (
        f"The macroeconomic environment presents "
        f"{'favourable' if risk_band in ('PRIME','LOW') else 'mixed'} conditions for {name}. "
        f"GST data with grade {gst_grade} supports "
        f"{'continued operations' if gst_grade in ('A','B') else 'cautious monitoring'}."
    )

    return {
        "CHARACTER": _section("CHARACTER", char_text),
        "CAPACITY": _section("CAPACITY", cap_text),
        "CAPITAL": _section("CAPITAL", cap_text2),
        "COLLATERAL": _section("COLLATERAL", coll_text),
        "CONDITIONS": _section("CONDITIONS", cond_text),
    }
