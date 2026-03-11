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


def export_graph_for_visualization(gst_dir: Path | None = None) -> dict[str, Any]:
    """
    Export complete graph data suitable for frontend visualization.
    
    Returns nodes, edges, circular patterns, and clusters in JSON-friendly format.
    """
    from src.gst.graph_builder import TransactionGraphBuilder

    builder = TransactionGraphBuilder(gst_dir=gst_dir)
    graph = builder.build_graph()

    # Compute risk scores
    node_risk = {}
    try:
        node_risk = builder.compute_node_risk_scores(graph)
    except Exception as exc:
        log.warning("Node risk scoring failed: %s", exc)

    # Find patterns
    circular = builder.find_circular_patterns(graph)
    clusters = builder.find_suspicious_clusters(graph)

    # Identify which nodes/edges are part of circular patterns
    circular_gstins = set()
    circular_edges = set()
    for pattern in circular:
        if pattern.get("flag") == "CIRCULAR_TRADING":
            for gstin in pattern.get("cycle", []):
                circular_gstins.add(gstin)
            cycle = pattern.get("cycle", [])
            for i in range(len(cycle)):
                src = cycle[i]
                dst = cycle[(i + 1) % len(cycle)]
                circular_edges.add((src, dst))

    # Identify suspicious nodes
    suspicious_gstins = set()
    for cluster in clusters:
        for gstin in cluster.get("nodes", []):
            suspicious_gstins.add(gstin)

    # Export nodes
    nodes = []
    for gstin in graph.nodes():
        node_data = graph.nodes[gstin]
        nodes.append({
            "id": gstin,
            "name": node_data.get("name", gstin[:15]),
            "total_sales": node_data.get("total_sales", 0.0),
            "total_purchases": node_data.get("total_purchases", 0.0),
            "net_gst_paid": node_data.get("net_gst_paid", 0.0),
            "risk_score": node_risk.get(gstin, 0.0),
            "is_circular": gstin in circular_gstins,
            "is_suspicious": gstin in suspicious_gstins,
            "sector": node_data.get("sector"),
            "state": node_data.get("state"),
        })

    # Export edges
    edges = []
    for src, dst, edge_data in graph.edges(data=True):
        edges.append({
            "source": src,
            "target": dst,
            "invoice_value": edge_data.get("invoice_value", 0.0),
            "tax_amount": edge_data.get("tax_amount", 0.0),
            "transaction_count": edge_data.get("transaction_count", 1),
            "is_circular": (src, dst) in circular_edges,
        })

    # Stats
    stats = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "circular_trading_nodes": len(circular_gstins),
        "suspicious_nodes": len(suspicious_gstins),
        "total_transaction_value": sum(e["invoice_value"] for e in edges),
        "avg_risk_score": sum(node_risk.values()) / len(node_risk) if node_risk else 0.0,
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "circular_patterns": circular,
        "suspicious_clusters": clusters,
        "stats": stats,
    }
