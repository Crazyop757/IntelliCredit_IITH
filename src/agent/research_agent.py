"""
research_agent.py — LangGraph multi-tool credit research agent for intelli_credit.

Orchestrates four intelligence tools in parallel (news, eCourts, MCA, RBI) via a
LangGraph StateGraph, then synthesises the results through a Claude-backed
SynthesizerAgent into a single structured credit opinion.

Public API
----------
    agent = ResearchAgent()
    result = agent.run_research(
        "Reliance Industries",
        company_cin="L17110MH1973PLC019786",
        director_names=["Mukesh Ambani"],
    )
    print(result["synthesis_report"])

Graph topology
--------------
    START → planner ──(Send×4, parallel)──► news_node   ─┐
                                          ► ecourts_node ─┤
                                          ► mca_node     ─┼─► synthesizer → END
                                          ► rbi_node     ─┘
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import operator
import os
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Project-root path resolution
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# LangGraph imports
# ---------------------------------------------------------------------------
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Send                    # noqa: E402

# ---------------------------------------------------------------------------
# Tool imports (lazy singletons below)
# ---------------------------------------------------------------------------
import anthropic  # noqa: E402

from src.agent.tools.news_tool     import NewsIntelligenceTool   # noqa: E402
from src.agent.tools.ecourts_tool  import ECourtsTool            # noqa: E402
from src.agent.tools.mca_tool      import MCATool                # noqa: E402
from src.agent.tools.rbi_tool      import RBIDefaulterTool       # noqa: E402
from src.agent.synthesizer         import SynthesizerAgent        # noqa: E402

logger = logging.getLogger("intelli_credit.agent.research_agent")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_NODE_TIMEOUT_SEC = 30          # max seconds any single node may run
_CLAUDE_MODEL     = "claude-haiku-4-5-20251001"   # fastest model available; update as needed

# ---------------------------------------------------------------------------
# Lazy tool singletons
# ---------------------------------------------------------------------------
_news_tool:    NewsIntelligenceTool | None = None
_ecourts_tool: ECourtsTool          | None = None
_mca_tool:     MCATool               | None = None
_rbi_tool:     RBIDefaulterTool      | None = None


def _get_news_tool() -> NewsIntelligenceTool:
    global _news_tool
    if _news_tool is None:
        _news_tool = NewsIntelligenceTool()
    return _news_tool


def _get_ecourts_tool() -> ECourtsTool:
    global _ecourts_tool
    if _ecourts_tool is None:
        _ecourts_tool = ECourtsTool()
    return _ecourts_tool


def _get_mca_tool() -> MCATool:
    global _mca_tool
    if _mca_tool is None:
        _mca_tool = MCATool()
    return _mca_tool


def _get_rbi_tool() -> RBIDefaulterTool:
    global _rbi_tool
    if _rbi_tool is None:
        _rbi_tool = RBIDefaulterTool()
    return _rbi_tool


# ---------------------------------------------------------------------------
# AgentState
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    """Full state object passed through the research graph."""

    company_name:      str
    company_cin:       str | None
    director_names:    list[str]

    # Reports written by the four parallel research nodes
    news_report:       dict[str, Any] | None
    ecourts_report:    dict[str, Any] | None
    mca_report:        dict[str, Any] | None
    rbi_report:        dict[str, Any] | None

    # Final synthesised credit opinion
    synthesis_report:  dict[str, Any] | None

    # Aggregated across all nodes (operator.add merges lists from parallel branches)
    error_log:         Annotated[list[str], operator.add]

    # Lifecycle status: initialised → planning_complete → research_complete → complete
    status:            str


# ---------------------------------------------------------------------------
# Timeout helper
# ---------------------------------------------------------------------------

def _run_with_timeout(fn, *args, timeout: float = _NODE_TIMEOUT_SEC, **kwargs) -> Any:
    """Run *fn* with a wall-clock timeout; raises ``concurrent.futures.TimeoutError``."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        return future.result(timeout=timeout)



# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

def planner_node(state: AgentState) -> dict[str, Any]:
    """
    Use Claude to normalise the company name and plan the research scope.
    If the API key is absent or the call times out, the raw inputs pass through unchanged.
    """
    company_name   = (state.get("company_name") or "").strip()
    company_cin    = state.get("company_cin")
    director_names = state.get("director_names") or []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("planner_node: ANTHROPIC_API_KEY not set — passing inputs through")
        return {"status": "planning_complete", "error_log": []}

    def _llm_call() -> str:
        client = anthropic.Anthropic(api_key=api_key)
        system = (
            "You are a credit research planner for an Indian NBFC. "
            "Given a company name and optional metadata, output ONLY a JSON object with keys: "
            "normalized_name (string — the canonical legal entity name if known, else the input), "
            "research_focus (list of strings — specific risk areas to investigate), "
            "additional_context (string — any relevant background you know)."
        )
        user_msg = (
            f"Company : {company_name}\n"
            f"CIN     : {company_cin or 'not provided'}\n"
            f"Directors: {', '.join(director_names) or 'not provided'}\n\n"
            "Plan the credit due-diligence research."
        )
        resp = client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": user_msg}],
            system=system,
        )
        return resp.content[0].text.strip()

    try:
        raw = _run_with_timeout(_llm_call, timeout=_NODE_TIMEOUT_SEC)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            plan     = json.loads(match.group())
            norm     = plan.get("normalized_name", "").strip()
            if norm:
                company_name = norm
        logger.info("planner_node: normalised company=%r", company_name)
        return {"company_name": company_name, "status": "planning_complete", "error_log": []}

    except concurrent.futures.TimeoutError:
        logger.warning("planner_node timed out after %ss", _NODE_TIMEOUT_SEC)
        return {
            "company_name": company_name,
            "status":       "planning_complete",
            "error_log":    [f"planner_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("planner_node error: %s", exc)
        return {
            "company_name": company_name,
            "status":       "planning_complete",
            "error_log":    [f"planner_node: {exc}"],
        }


# ------------------------------------------------------------------
def _dispatch_research(state: AgentState) -> list[Send]:
    """Conditional-edge function: fan out to all four research nodes in parallel."""
    return [
        Send("news_node",    dict(state)),
        Send("ecourts_node", dict(state)),
        Send("mca_node",     dict(state)),
        Send("rbi_node",     dict(state)),
    ]


# ------------------------------------------------------------------
def news_node(state: AgentState) -> dict[str, Any]:
    """Call NewsIntelligenceTool and write result into news_report."""
    company_name   = state["company_name"]
    director_names = state.get("director_names") or []
    logger.info("news_node: company=%r", company_name)

    try:
        def _call():
            return _get_news_tool().search_company_news(
                company_name, promoter_names=director_names,
            )

        report = _run_with_timeout(_call, timeout=_NODE_TIMEOUT_SEC)
        return {"news_report": report, "error_log": []}

    except concurrent.futures.TimeoutError:
        logger.warning("news_node: timed out")
        return {
            "news_report": {"error": "timeout", "data_source": "error"},
            "error_log":   [f"news_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("news_node: error — %s", exc)
        return {
            "news_report": {"error": str(exc), "data_source": "error"},
            "error_log":   [f"news_node: {exc}"],
        }


# ------------------------------------------------------------------
def ecourts_node(state: AgentState) -> dict[str, Any]:
    """Call ECourtsTool and write result into ecourts_report."""
    company_name = state["company_name"]
    logger.info("ecourts_node: company=%r", company_name)

    try:
        def _call():
            return _get_ecourts_tool().search_cases(company_name)

        report = _run_with_timeout(_call, timeout=_NODE_TIMEOUT_SEC)
        return {"ecourts_report": report, "error_log": []}

    except concurrent.futures.TimeoutError:
        logger.warning("ecourts_node: timed out")
        return {
            "ecourts_report": {"error": "timeout", "data_source": "error"},
            "error_log":      [f"ecourts_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("ecourts_node: error — %s", exc)
        return {
            "ecourts_report": {"error": str(exc), "data_source": "error"},
            "error_log":      [f"ecourts_node: {exc}"],
        }


# ------------------------------------------------------------------
def mca_node(state: AgentState) -> dict[str, Any]:
    """Call MCATool (master + charges) and write result into mca_report."""
    company_name = state["company_name"]
    company_cin  = state.get("company_cin")
    query        = (company_cin or company_name).strip()
    logger.info("mca_node: query=%r", query)

    try:
        def _call():
            tool    = _get_mca_tool()
            master  = tool.get_company_master(query)
            # Use MCA-returned CIN if available, else fall back to input
            cin     = master.get("cin") or company_cin or ""
            charges = tool.get_charges(cin) if cin else {}
            return {**master, "charges": charges}

        report = _run_with_timeout(_call, timeout=_NODE_TIMEOUT_SEC)
        return {"mca_report": report, "error_log": []}

    except concurrent.futures.TimeoutError:
        logger.warning("mca_node: timed out")
        return {
            "mca_report": {"error": "timeout", "data_source": "error"},
            "error_log":  [f"mca_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("mca_node: error — %s", exc)
        return {
            "mca_report": {"error": str(exc), "data_source": "error"},
            "error_log":  [f"mca_node: {exc}"],
        }


# ------------------------------------------------------------------
def rbi_node(state: AgentState) -> dict[str, Any]:
    """Call RBIDefaulterTool and write result into rbi_report."""
    company_name   = state["company_name"]
    director_names = state.get("director_names") or []
    logger.info("rbi_node: company=%r directors=%r", company_name, director_names)

    try:
        def _call():
            return _get_rbi_tool().check_company_group(
                company_name, director_names=director_names,
            )

        report = _run_with_timeout(_call, timeout=_NODE_TIMEOUT_SEC)
        return {"rbi_report": report, "error_log": []}

    except concurrent.futures.TimeoutError:
        logger.warning("rbi_node: timed out")
        return {
            "rbi_report": {"error": "timeout", "data_source": "error"},
            "error_log":  [f"rbi_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("rbi_node: error — %s", exc)
        return {
            "rbi_report": {"error": str(exc), "data_source": "error"},
            "error_log":  [f"rbi_node: {exc}"],
        }


# ------------------------------------------------------------------
def synthesizer_node(state: AgentState) -> dict[str, Any]:
    """Combine the four reports into a unified credit opinion via SynthesizerAgent."""
    company_name = state["company_name"]
    logger.info("synthesizer_node: company=%r", company_name)

    try:
        def _call():
            agent = SynthesizerAgent()
            syn   = agent.synthesize(
                news_report=state.get("news_report"),
                ecourts_report=state.get("ecourts_report"),
                mca_report=state.get("mca_report"),
                rbi_report=state.get("rbi_report"),
            )
            _score, report = agent.compute_external_score(syn)
            return report

        report = _run_with_timeout(_call, timeout=_NODE_TIMEOUT_SEC)
        return {
            "synthesis_report": report,
            "status":           "complete",
            "error_log":        [],
        }

    except concurrent.futures.TimeoutError:
        logger.warning("synthesizer_node: timed out")
        return {
            "synthesis_report": {"error": "timeout"},
            "status":           "error",
            "error_log":        [f"synthesizer_node: timed out after {_NODE_TIMEOUT_SEC}s"],
        }
    except Exception as exc:
        logger.warning("synthesizer_node: error — %s", exc)
        return {
            "synthesis_report": {"error": str(exc)},
            "status":           "error",
            "error_log":        [f"synthesizer_node: {traceback.format_exc()}"],
        }


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    # Register nodes
    g.add_node("planner",      planner_node)
    g.add_node("news_node",    news_node)
    g.add_node("ecourts_node", ecourts_node)
    g.add_node("mca_node",     mca_node)
    g.add_node("rbi_node",     rbi_node)
    g.add_node("synthesizer",  synthesizer_node)

    # Entry point
    g.set_entry_point("planner")

    # Planner → parallel research nodes (Send-based fan-out)
    g.add_conditional_edges(
        "planner",
        _dispatch_research,
        ["news_node", "ecourts_node", "mca_node", "rbi_node"],
    )

    # Fan-in: each research node → synthesizer
    for _node in ("news_node", "ecourts_node", "mca_node", "rbi_node"):
        g.add_edge(_node, "synthesizer")

    g.add_edge("synthesizer", END)

    return g


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------

class ResearchAgent:
    """
    Orchestrates multi-source credit research via a compiled LangGraph graph.

    Usage
    -----
        agent = ResearchAgent()
        state = agent.run_research(
            "Reliance Industries",
            company_cin="L17110MH1973PLC019786",
            director_names=["Mukesh Ambani"],
        )
        print(state["synthesis_report"])
    """

    def __init__(self) -> None:
        self._compiled = _build_graph().compile()

    # ------------------------------------------------------------------
    def run_research(
        self,
        company_name:   str,
        company_cin:    str | None = None,
        director_names: list[str]  | None = None,
    ) -> AgentState:
        """
        Run the full research pipeline and return the final AgentState.

        Parameters
        ----------
        company_name :
            Company name to research (required).
        company_cin :
            MCA CIN (e.g. ``"L17110MH1973PLC019786"``), optional.
        director_names :
            List of director / promoter names to screen, optional.

        Returns
        -------
        AgentState — final state including synthesis_report, individual
        tool reports, error_log, and status.

        Raises
        ------
        ValueError : if company_name is empty.
        """
        if not company_name or not company_name.strip():
            raise ValueError("company_name must not be empty")

        initial: AgentState = {
            "company_name":    company_name.strip(),
            "company_cin":     company_cin,
            "director_names":  list(director_names or []),
            "news_report":     None,
            "ecourts_report":  None,
            "mca_report":      None,
            "rbi_report":      None,
            "synthesis_report": None,
            "error_log":       [],
            "status":          "initialised",
        }

        logger.info(
            "ResearchAgent.run_research: company=%r  cin=%r  directors=%r",
            company_name, company_cin, director_names,
        )
        return self._compiled.invoke(initial)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    parser = argparse.ArgumentParser(description="Run ResearchAgent on a company")
    parser.add_argument("company",   nargs="?",  default="Reliance Industries",
                        help="Company name to research")
    parser.add_argument("--cin",     default=None, help="MCA CIN (optional)")
    parser.add_argument("--director",action="append", default=[],
                        dest="directors", metavar="NAME",
                        help="Director name (repeatable)")
    args = parser.parse_args()

    agent = ResearchAgent()
    print(f"\n{'='*60}")
    print(f"  Credit Research: {args.company}")
    print(f"{'='*60}")

    result = agent.run_research(
        args.company,
        company_cin=args.cin,
        director_names=args.directors,
    )

    syn = result.get("synthesis_report") or {}
    print(f"\nOverall Risk  : {syn.get('overall_risk_level', 'N/A')}")
    print(f"Recommended   : {syn.get('recommended_action', 'N/A')}")
    print(f"Confidence    : {syn.get('confidence_score', 0):.0%}")
    print(f"\nSummary:\n  {syn.get('risk_summary', '')}")

    red_flags = syn.get("red_flags") or []
    if red_flags:
        print("\nRed Flags:")
        for f in red_flags:
            print(f"  • {f}")

    positives = syn.get("positive_signals") or []
    if positives:
        print("\nPositive Signals:")
        for s in positives:
            print(f"  ✓ {s}")

    errors = result.get("error_log") or []
    if errors:
        print("\nErrors during research:")
        for e in errors:
            print(f"  [!] {e}")

    print(f"\nStatus: {result.get('status')}")
    print(f"{'='*60}\n")
