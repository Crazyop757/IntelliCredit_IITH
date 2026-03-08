"""
GST service — reconciliation, EWS, GNN, graph operations.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def run_reconciliation(company_id: str, gst_dir: Path | None = None) -> dict[str, Any]:
    """Full ITC + turnover + fictitious-vendor + health-score reconciliation."""
    from src.gst.reconciler import GSTReconciler

    reconciler = GSTReconciler(gst_dir=gst_dir)
    report = reconciler.run_full_reconciliation(company_id)
    return report


def run_ews(company_id: str, gst_dir: Path | None = None) -> dict[str, Any]:
    """EWS engine — 8 flags + SMA classification (reads from Silver layer)."""
    from src.gst.ews_engine import EWSEngine

    engine = EWSEngine(gst_dir=gst_dir)
    report = engine.consolidate_signals(company_id)
    return report


def run_gnn_predict(
    company_id: str,
    gst_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Build transaction graph and predict circular-trading fraud via GNN.
    """
    from src.gst.graph_builder import TransactionGraphBuilder
    from src.gst.gnn_detector import CircularTradingDetector
    from src.api.config import settings

    builder = TransactionGraphBuilder(gst_dir=gst_dir)
    graph = builder.build_graph()

    detector = CircularTradingDetector(model_path=settings.model_path)
    predictions = detector.predict_fraud(graph)

    circular = builder.find_circular_patterns(graph)
    clusters = builder.find_suspicious_clusters(graph)

    pred_list = []
    for gstin, info in predictions.items():
        label = (
            "HIGH_RISK"
            if info.get("fraud_probability", 0) >= 0.70
            else "MEDIUM_RISK"
            if info.get("fraud_probability", 0) >= 0.40
            else "LOW_RISK"
        )
        pred_list.append(
            {
                "gstin": gstin,
                "fraud_probability": info.get("fraud_probability", 0.0),
                "risk_label": label,
            }
        )

    return {
        "company_id": company_id,
        "predictions": pred_list,
        "circular_patterns": circular,
        "suspicious_clusters": clusters,
    }


def build_graph(gst_dir: Path | None = None, visualize: bool = False) -> dict[str, Any]:
    """Build and optionally visualize the full GSTIN transaction graph."""
    from src.gst.graph_builder import TransactionGraphBuilder
    from src.api.config import settings

    builder = TransactionGraphBuilder(gst_dir=gst_dir)
    graph = builder.build_graph()

    viz_path = None
    if visualize:
        out = settings.outputs_dir / "gst_graph.png"
        try:
            builder.visualize_graph(out)
            viz_path = str(out)
        except Exception as exc:
            log.warning("Graph visualization failed: %s", exc)

    node_risk = {}
    try:
        node_risk = builder.compute_node_risk_scores(graph)
    except Exception as exc:
        log.warning("Node risk scoring failed: %s", exc)

    circular = builder.find_circular_patterns(graph)
    clusters = builder.find_suspicious_clusters(graph)

    return {
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "circular_pattern_count": len(circular),
        "suspicious_cluster_count": len(clusters),
        "node_risk_scores": node_risk,
        "visualization_path": viz_path,
    }
