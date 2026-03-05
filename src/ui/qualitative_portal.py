"""
qualitative_portal.py — Credit Officer Qualitative Due-Diligence Portal.

Streamlit single-page form that captures on-ground Credit Officer observations
across three sections (Facility Visit, Management Interview, On-ground
Verification), computes a qualitative risk adjustment via QualitativeScorer,
and persists the enriched record to the Silver layer.

Run
---
    streamlit run src/ui/qualitative_portal.py

Session-state contract (consumed from upstream pages)
------------------------------------------------------
    st.session_state["company_name"]   str   e.g. "Reliance Industries Ltd"
    st.session_state["company_cin"]    str   e.g. "L17110MH1973PLC019786"

Both keys fall back gracefully when absent (demo / standalone mode).
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Project-root path bootstrap (works whether launched from repo root or src/)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.scorer.qualitative_scorer import QualitativeScorer  # noqa: E402

logger = logging.getLogger("intelli_credit.ui.qualitative_portal")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SILVER_QUALITATIVE_DIR = _PROJECT_ROOT / "data" / "silver" / "qualitative_inputs"
_SILVER_QUALITATIVE_DIR.mkdir(parents=True, exist_ok=True)

_SCORER = QualitativeScorer()

# Colour palette for severity badges
_SEVERITY_STYLE: dict[str, tuple[str, str]] = {
    # severity         background   text
    "HIGH_RISK":     ("#FF4B4B",   "#FFFFFF"),
    "MODERATE_RISK": ("#FFA500",   "#FFFFFF"),
    "NEUTRAL":       ("#888888",   "#FFFFFF"),
    "POSITIVE":      ("#21A35F",   "#FFFFFF"),
}

# Arrow indicators: negative total = risk worsened (▼), positive = risk improved (▲)
_DELTA_ARROW: dict[str, str] = {
    "HIGH_RISK":     "▼▼",
    "MODERATE_RISK": "▼",
    "NEUTRAL":       "—",
    "POSITIVE":      "▲",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_to_silver(company_name: str, company_cin: str, form_data: dict, result: dict) -> Path:
    """
    Persist the form submission + scoring result as a JSON-line record in the
    Silver layer under  data/silver/qualitative_inputs/<company_cin>.jsonl

    Falls back to  <company_name_slug>.jsonl  when CIN is absent.
    """
    slug = (company_cin or company_name).replace(" ", "_").strip()[:60]
    filepath = _SILVER_QUALITATIVE_DIR / f"{slug}.jsonl"

    record = {
        "record_id":    str(uuid.uuid4()),
        "company_name": company_name,
        "company_cin":  company_cin,
        "submitted_at": _now_utc(),
        "form_data":    form_data,
        "scoring":      result,
    }

    with filepath.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info("Qualitative record saved → %s", filepath)
    return filepath


def _severity_badge(severity: str) -> str:
    """Return an HTML badge for the given severity label."""
    bg, fg = _SEVERITY_STYLE.get(severity, ("#666666", "#FFFFFF"))
    label  = severity.replace("_", " ")
    return (
        f'<span style="background:{bg}; color:{fg}; padding:3px 10px; '
        f'border-radius:4px; font-weight:600; font-size:0.85em;">{label}</span>'
    )


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

def render() -> None:
    st.set_page_config(
        page_title="Qualitative Due-Diligence Portal",
        page_icon="🏭",
        layout="wide",
    )

    # ---- Header -----------------------------------------------------------
    company_name: str = st.session_state.get("company_name", "Demo Company Ltd")
    company_cin:  str = st.session_state.get("company_cin",  "")

    st.title("Primary Due Diligence Inputs — Credit Officer Portal")
    st.caption(
        f"**Company:** {company_name}"
        + (f"  ·  **CIN:** {company_cin}" if company_cin else "")
    )
    st.divider()

    # ---- Form -------------------------------------------------------------
    with st.form("qualitative_form", clear_on_submit=False):

        # ==================================================================
        # Section A — Factory / Facility Visit
        # ==================================================================
        st.subheader("Section A — Factory / Facility Visit")

        site_visit_observations = st.text_area(
            "Site Visit Observations",
            placeholder=(
                "e.g., Factory operating at approximately 40% capacity. "
                "Workers present but machinery appeared dated."
            ),
            height=130,
            help="Describe what you observed during the physical site visit.",
        )

        col_a1, col_a2 = st.columns([2, 1])

        with col_a1:
            capacity_utilization = st.slider(
                "Estimated Capacity Utilization %",
                min_value=0,
                max_value=100,
                value=70,
                step=5,
                help="Your estimate of current operating capacity vs installed capacity.",
            )

        with col_a2:
            facility_condition = st.selectbox(
                "Overall Facility Condition",
                options=["Excellent", "Good", "Fair", "Poor", "Not Visited"],
                index=1,   # default: Good
                help="Overall physical condition of the factory / facility.",
            )

        st.divider()

        # ==================================================================
        # Section B — Management Interview
        # ==================================================================
        st.subheader("Section B — Management Interview")

        management_interview_notes = st.text_area(
            "Management Interview Notes",
            placeholder=(
                "e.g., MD provided audited financials for FY24. CFO was present "
                "and explained the working-capital cycle in detail."
            ),
            height=130,
            help="Summarise key points from the management meeting.",
        )

        management_transparency = st.selectbox(
            "Management Transparency Level",
            options=[
                "Fully Transparent",
                "Mostly Transparent",
                "Evasive on some topics",
                "Uncooperative",
            ],
            index=0,
            help="Your assessment of how forthcoming management was during the interview.",
        )

        group_company_exposure = st.text_area(
            "Group Company Exposure Noted",
            placeholder=(
                "e.g., Management mentioned two group entities — XYZ Traders and "
                "ABC Holdings — not reflected in the submitted documents."
            ),
            height=90,
            help="Any undisclosed group entities or related-party exposures mentioned.",
        )

        st.divider()

        # ==================================================================
        # Section C — On-ground Verification
        # ==================================================================
        st.subheader("Section C — On-ground Verification")

        col_c1, col_c2 = st.columns(2)

        with col_c1:
            inventory_vs_records = st.selectbox(
                "Inventory Level vs Records",
                options=[
                    "Matches",
                    "Slightly Lower",
                    "Significantly Lower",
                    "Could Not Verify",
                ],
                index=0,
                help="Physical inventory count vs figures in submitted stock statements.",
            )

        with col_c2:
            employee_count_vs_records = st.selectbox(
                "Employee Count vs HR Records",
                options=[
                    "Matches",
                    "20% Lower",
                    "50%+ Lower",
                    "Could Not Verify",
                ],
                index=0,
                help="Headcount observed on-site vs HR records submitted.",
            )

        other_key_observations = st.text_area(
            "Other Key Observations",
            placeholder=(
                "e.g., Raw material storage appeared adequate for ~3 weeks of production. "
                "No visible pending maintenance issues."
            ),
            height=100,
            help="Any other material observations not covered in the sections above.",
        )

        st.divider()

        submitted = st.form_submit_button(
            "Submit Due Diligence Inputs",
            type="primary",
            use_container_width=True,
        )

    # ---- Post-submission logic --------------------------------------------
    if submitted:
        form_data = {
            # Section A
            "site_visit_observations":  site_visit_observations,
            "capacity_utilization":     capacity_utilization,
            "facility_condition":       facility_condition,
            # Section B
            "management_interview_notes": management_interview_notes,
            "management_transparency":    management_transparency,
            "group_company_exposure":     group_company_exposure,
            # Section C
            "inventory_vs_records":       inventory_vs_records,
            "employee_count_vs_records":  employee_count_vs_records,
            "other_key_observations":     other_key_observations,
        }

        with st.spinner("Computing qualitative risk adjustment…"):
            result = _SCORER.compute_adjustment(form_data)

        _display_result(result, form_data, company_name, company_cin)


def _display_result(
    result: dict,
    form_data: dict,
    company_name: str,
    company_cin: str,
) -> None:
    """Render scoring result panel and persist to Silver layer."""

    total:    float = result["total_adjustment"]
    severity: str   = result["severity"]
    arrow:    str   = _DELTA_ARROW.get(severity, "")

    bg, fg = _SEVERITY_STYLE.get(severity, ("#888888", "#FFFFFF"))

    st.markdown("---")
    st.subheader("Qualitative Assessment Result")

    # ---- Primary metric card ---------------------------------------------
    st.markdown(
        f"""
        <div style="
            background:{bg};
            color:{fg};
            border-radius:8px;
            padding:20px 28px;
            margin-bottom:12px;
        ">
            <div style="font-size:1.0em; font-weight:500; opacity:0.9;">
                Qualitative Adjustment Applied
            </div>
            <div style="font-size:2.4em; font-weight:700; line-height:1.2;">
                {arrow} {total:+.2f} points to risk score
            </div>
            <div style="font-size:1.0em; margin-top:6px; opacity:0.9;">
                {severity.replace("_", " ").title()}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- Summary narrative -----------------------------------------------
    st.info(result["summary_text"])

    # ---- AI Red Flags ----------------------------------------------------
    red_flags = result.get("red_flags_found", [])
    if red_flags:
        st.error(f"**{len(red_flags)} AI-Identified Red Flag(s) in Free-Text Notes**")
        for rf in red_flags:
            field_label = rf["field"].replace("_", " ").title()
            st.markdown(f"- **{field_label}**: {rf['reason']}")

    # ---- Score Breakdown expander ----------------------------------------
    with st.expander("Score Breakdown by Component", expanded=False):
        breakdown = result["breakdown"]

        # Display names for all possible breakdown keys
        col_names = {
            "capacity_utilization":              "Capacity Utilization",
            "facility_condition":                "Facility Condition",
            "management_transparency":           "Management Transparency",
            "inventory_vs_records":              "Inventory vs Records",
            "employee_count_vs_records":         "Employee Count vs Records",
            "site_visit_observations_text":      "Site Visit Notes (AI)",
            "management_interview_notes_text":   "Interview Notes (AI)",
            "group_company_exposure_text":       "Group Exposure Notes (AI)",
            "other_key_observations_text":       "Other Observations (AI)",
        }

        for key, label in col_names.items():
            val = breakdown.get(key)
            if val is None:
                continue
            # negative = bad → red ▼ ;  positive = good → green ▲
            indicator = "▼" if val < 0 else ("▲" if val > 0 else "—")
            color     = "red" if val < 0 else ("green" if val > 0 else "gray")
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(label)
            c2.write(f"{val:+.2f}")
            c3.markdown(f":{color}[{indicator}]")

        st.caption(
            f"Raw (uncapped) total: **{result['raw_total']:+.2f}**  ·  "
            f"Applied (clamped −5 → +2): **{total:+.2f}**"
        )

    # ---- Save to Silver --------------------------------------------------
    try:
        saved_path = _save_to_silver(company_name, company_cin, form_data, result)
        st.success(f"Record saved to Silver layer → `{saved_path.relative_to(_PROJECT_ROOT)}`")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Could not save record: {exc}")


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    render()
else:
    # Streamlit imports the module; call render() at module scope.
    render()
