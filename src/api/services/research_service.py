"""
Research agent service.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def run_research(
    company_name: str,
    company_cin: str | None = None,
    director_names: list[str] | None = None,
) -> dict[str, Any]:
    """Run the full LangGraph research agent and return a structured report."""
    from src.agent.research_agent import ResearchAgent
    from src.agent.synthesizer import SynthesizerAgent

    agent = ResearchAgent()
    state = agent.run_research(
        company_name=company_name,
        company_cin=company_cin,
        director_names=director_names or [],
    )

    synthesis = state.get("synthesis_report") or {}
    synth_agent = SynthesizerAgent()
    final_score, enriched = synth_agent.compute_external_score(synthesis)

    prf = synthesis.get("promoter_risk_flag")
    if isinstance(prf, str):
        prf = {"level": prf}

    return {
        "company_name": company_name,
        "overall_external_risk_score": final_score,
        "promoter_risk_flag": prf,
        "litigation_summary": synthesis.get("litigation_summary"),
        "news_summary": synthesis.get("news_summary"),
        "regulatory_compliance_summary": synthesis.get("regulatory_compliance_summary"),
        "key_red_flags": synthesis.get("key_red_flags", []),
        "positive_signals": synthesis.get("positive_signals", []),
        "recommended_action": synthesis.get("recommended_action"),
        "recommended_rationale": synthesis.get("recommended_rationale"),
        "synthesis_method": synthesis.get("synthesis_method"),
        "news_report": state.get("news_report"),
        "ecourts_report": state.get("ecourts_report"),
        "mca_report": state.get("mca_report"),
        "rbi_report": state.get("rbi_report"),
    }


def synthesize_reports(
    news_report: dict | None = None,
    ecourts_report: dict | None = None,
    mca_report: dict | None = None,
    rbi_report: dict | None = None,
) -> dict[str, Any]:
    """Synthesize pre-fetched sub-reports without running the full agent."""
    from src.agent.synthesizer import SynthesizerAgent

    agent = SynthesizerAgent()
    synthesis = agent.synthesize(
        news_report=news_report,
        ecourts_report=ecourts_report,
        mca_report=mca_report,
        rbi_report=rbi_report,
    )
    final_score, enriched = agent.compute_external_score(synthesis)

    prf = synthesis.get("promoter_risk_flag")
    if isinstance(prf, str):
        prf = {"level": prf}

    return {
        "overall_external_risk_score": final_score,
        "promoter_risk_flag": prf,
        "litigation_summary": synthesis.get("litigation_summary"),
        "news_summary": synthesis.get("news_summary"),
        "regulatory_compliance_summary": synthesis.get("regulatory_compliance_summary"),
        "key_red_flags": synthesis.get("key_red_flags", []),
        "positive_signals": synthesis.get("positive_signals", []),
        "recommended_action": synthesis.get("recommended_action"),
        "synthesis_method": synthesis.get("synthesis_method"),
    }
