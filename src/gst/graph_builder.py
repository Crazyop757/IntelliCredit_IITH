"""
graph_builder.py — NetworkX-based GST transaction graph analysis for intelli_credit.

TransactionGraphBuilder ingests multi-company GSTR data (or the combined
``gst_transaction_graph.json`` produced by GSTDataGenerator) and provides:

  1. Graph construction        – directed graph of GSTIN → GSTIN invoice edges
  2. Circular-pattern detection – DFS cycle detection via networkx.simple_cycles
  3. Suspicious-cluster detection – shared attributes across connected components
  4. Node risk scoring         – PageRank + anomaly flags → 0-1 risk score
  5. Graph visualisation        – matplotlib plot saved to disk

The module can also be used stand-alone (``python -m src.gst.graph_builder``)
to analyse the data already in ``data/raw/gst/``.
"""

from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger("intelli_credit.gst.graph_builder")

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
GST_RAW_DIR   = _PROJECT_ROOT / "data" / "raw" / "gst"
OUTPUT_DIR    = _PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
_CIRCULAR_MAX_CYCLE_LEN    = 5          # longer rings are usually coincidences
_CIRCULAR_MIN_CYCLE_VALUE  = 100_000.0  # INR; below this is noise
_CIRCULAR_VALUE_SPREAD_PCT = 10.0       # edge values within ±10% = suspicious
_HIGH_PAGERANK_PERCENTILE  = 0.80       # top 20% → elevated centrality flag


# ===========================================================================
# TransactionGraphBuilder
# ===========================================================================

class TransactionGraphBuilder:
    """
    Build and analyse a directed GST transaction graph.

    Parameters
    ----------
    gst_dir:
        Directory containing GST JSON files.  Defaults to ``data/raw/gst/``.

    Example
    -------
    >>> builder = TransactionGraphBuilder()
    >>> graph, risk_scores = builder.run_full_analysis()
    >>> builder.visualize_graph("outputs/gst_graph.png")
    """

    def __init__(self, gst_dir: Path | str | None = None) -> None:
        self.gst_dir = Path(gst_dir) if gst_dir else GST_RAW_DIR
        self.graph: nx.DiGraph | None = None
        self._risk_scores: dict[str, float] = {}
        self._circular_cycles: list[dict] = []
        self._suspicious_clusters: list[dict] = []

    # ------------------------------------------------------------------
    # 1. Graph construction
    # ------------------------------------------------------------------

    def build_graph(
        self,
        all_companies_gst_data: list[dict[str, Any]] | None = None,
    ) -> nx.DiGraph:
        """
        Build a directed graph from GST invoice data.

        Parameters
        ----------
        all_companies_gst_data:
            List of per-company dicts, each with keys ``"gstr1"``, ``"gstr2a"``,
            ``"gstr3b"`` (as returned by
            :meth:`~src.gst.data_generator.GSTDataGenerator.generate_company_data`
            or :meth:`~src.gst.reconciler.GSTReconciler.load_gst_data`).
            When ``None``, the pre-built ``gst_transaction_graph.json`` in
            ``gst_dir`` is used instead.

        Returns
        -------
        nx.DiGraph
            Nodes = unique GSTINs; directed edges = invoice transactions.

            **Node attributes**:
            ``total_sales``, ``total_purchases``, ``net_gst_paid``,
            ``sector`` (placeholder), ``registration_date`` (placeholder),
            ``gstin``.

            **Edge attributes**:
            ``invoice_value``, ``tax_amount``, ``date``, ``invoice_id``,
            ``period``, ``igst``, ``cgst``, ``sgst``.
            Multi-edges between the same pair of GSTINs are collapsed into a
            single edge whose ``invoice_value`` is the sum; ``invoice_id``
            becomes a list and ``date`` is the most-recent.
        """
        G = nx.DiGraph()

        if all_companies_gst_data is not None:
            edges_raw = self._edges_from_company_data(all_companies_gst_data)
            nodes_raw = self._nodes_from_company_data(all_companies_gst_data)
        else:
            edges_raw, nodes_raw = self._load_from_graph_file()

        # --- Add / update nodes -------------------------------------------
        for gstin, attrs in nodes_raw.items():
            G.add_node(gstin, **attrs)

        # --- Collapse multi-edges and add to graph ------------------------
        # key: (supplier_gstin, buyer_gstin) → accumulated attrs
        edge_acc: dict[tuple[str, str], dict] = {}

        for inv in edges_raw:
            sup  = inv["supplier_gstin"]
            buy  = inv["buyer_gstin"]
            key  = (sup, buy)
            tax  = inv.get("igst", 0.0) + inv.get("cgst", 0.0) + inv.get("sgst", 0.0)
            val  = inv.get("taxable_value", 0.0)

            # Ensure both endpoint nodes exist
            for gstin in (sup, buy):
                if gstin not in G:
                    G.add_node(
                        gstin,
                        gstin=gstin,
                        total_sales=0.0,
                        total_purchases=0.0,
                        net_gst_paid=0.0,
                        sector="Unknown",
                        registration_date=None,
                    )

            if key not in edge_acc:
                edge_acc[key] = {
                    "invoice_value": 0.0,
                    "tax_amount":    0.0,
                    "invoice_ids":   [],
                    "date":          inv.get("invoice_date", inv.get("period", "")),
                    "period":        inv.get("period", ""),
                    "igst":          0.0,
                    "cgst":          0.0,
                    "sgst":          0.0,
                    "circular_fraud": inv.get("circular_fraud", False),
                    "transaction_count": 0,
                }
            acc = edge_acc[key]
            acc["invoice_value"]    += val
            acc["tax_amount"]       += tax
            acc["igst"]             += inv.get("igst", 0.0)
            acc["cgst"]             += inv.get("cgst", 0.0)
            acc["sgst"]             += inv.get("sgst", 0.0)
            acc["invoice_ids"].append(inv.get("invoice_number", ""))
            acc["transaction_count"] += 1
            # Keep most-recent invoice date
            inv_date = inv.get("invoice_date", inv.get("period", ""))
            if inv_date > acc["date"]:
                acc["date"] = inv_date
            if inv.get("circular_fraud", False):
                acc["circular_fraud"] = True

        for (sup, buy), attrs in edge_acc.items():
            attrs["invoice_id"] = attrs.pop("invoice_ids")  # rename for clarity
            attrs["invoice_value"] = round(attrs["invoice_value"], 2)
            attrs["tax_amount"]    = round(attrs["tax_amount"], 2)
            attrs["igst"]          = round(attrs["igst"], 2)
            attrs["cgst"]          = round(attrs["cgst"], 2)
            attrs["sgst"]          = round(attrs["sgst"], 2)
            G.add_edge(sup, buy, **attrs)

        # --- Update node totals from edges (supplement loaded data) -------
        for gstin in G.nodes:
            out_val = sum(
                d["invoice_value"]
                for _, _, d in G.out_edges(gstin, data=True)
            )
            in_val  = sum(
                d["invoice_value"]
                for _, _, d in G.in_edges(gstin, data=True)
            )
            out_tax = sum(
                d["tax_amount"]
                for _, _, d in G.out_edges(gstin, data=True)
            )
            in_tax  = sum(
                d["tax_amount"]
                for _, _, d in G.in_edges(gstin, data=True)
            )
            node = G.nodes[gstin]
            node["total_sales"]     = round(out_val, 2)
            node["total_purchases"] = round(in_val,  2)
            node["net_gst_paid"]    = round(out_tax - in_tax, 2)

        self.graph = G
        logger.info(
            "Graph built: %d nodes, %d edges", G.number_of_nodes(), G.number_of_edges()
        )
        return G

    # ------------------------------------------------------------------
    # 2. Circular-pattern detection
    # ------------------------------------------------------------------

    def find_circular_patterns(
        self, graph: nx.DiGraph | None = None
    ) -> list[dict[str, Any]]:
        """
        Detect circular trading patterns using :func:`networkx.simple_cycles`.

        A cycle is flagged as **CIRCULAR_TRADING** when:

        * ``cycle_length`` ≤ :data:`_CIRCULAR_MAX_CYCLE_LEN` (default 5)
        * ``cycle_value``  ≥ :data:`_CIRCULAR_MIN_CYCLE_VALUE` (default ₹1 lakh)
        * All edge values in the cycle are within ±:data:`_CIRCULAR_VALUE_SPREAD_PCT`
          % of each other (carousel behaviour — same invoiced amount recycled).

        Returns
        -------
        list[dict]
            Each dict contains ``cycle``, ``cycle_length``, ``cycle_value``,
            ``value_spread_pct``, ``all_values_similar``, ``flag``,
            ``edges``.
        """
        G = graph if graph is not None else self._require_graph()
        results: list[dict] = []

        for cycle_nodes in nx.simple_cycles(G):
            n = len(cycle_nodes)
            if n > _CIRCULAR_MAX_CYCLE_LEN:
                continue

            # Collect edge data for consecutive node pairs in the ring
            edge_values: list[float] = []
            edge_details: list[dict] = []
            valid = True

            for i in range(n):
                src = cycle_nodes[i]
                dst = cycle_nodes[(i + 1) % n]
                if not G.has_edge(src, dst):
                    valid = False
                    break
                edata = G.edges[src, dst]
                edge_values.append(edata["invoice_value"])
                edge_details.append({
                    "supplier_gstin": src,
                    "buyer_gstin":    dst,
                    "invoice_value":  edata["invoice_value"],
                    "tax_amount":     edata["tax_amount"],
                    "transaction_count": edata.get("transaction_count", 1),
                })

            if not valid or not edge_values:
                continue

            cycle_value   = sum(edge_values)
            mean_val      = cycle_value / len(edge_values)
            spread_pct    = (
                (max(edge_values) - min(edge_values)) / mean_val * 100
                if mean_val > 0
                else 0.0
            )
            similar_values = spread_pct <= _CIRCULAR_VALUE_SPREAD_PCT

            flag = (
                "CIRCULAR_TRADING"
                if (
                    cycle_value >= _CIRCULAR_MIN_CYCLE_VALUE
                    and similar_values
                )
                else "POTENTIAL_CYCLE"
            )

            results.append({
                "cycle":              cycle_nodes,
                "cycle_length":       n,
                "cycle_value":        round(cycle_value, 2),
                "mean_edge_value":    round(mean_val, 2),
                "value_spread_pct":   round(spread_pct, 2),
                "all_values_similar": similar_values,
                "flag":               flag,
                "edges":              edge_details,
            })

        # Sort: CIRCULAR_TRADING first, then by descending cycle_value
        results.sort(
            key=lambda r: (r["flag"] != "CIRCULAR_TRADING", -r["cycle_value"])
        )

        self._circular_cycles = results
        logger.info(
            "Cycle detection: %d cycles found (%d CIRCULAR_TRADING)",
            len(results),
            sum(1 for r in results if r["flag"] == "CIRCULAR_TRADING"),
        )
        return results

    # ------------------------------------------------------------------
    # 3. Suspicious-cluster detection
    # ------------------------------------------------------------------

    def find_suspicious_clusters(
        self,
        graph: nx.DiGraph | None = None,
        node_metadata: dict[str, dict] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Identify suspicious clusters of GSTINs via connected-component analysis.

        A cluster is flagged when any of the following shared-attribute
        conditions is detected among nodes in the same weakly-connected
        component:

        * **Shared bank account** – ``bank_account`` node attribute appears
          on ≥ 2 nodes in the component.
        * **Shared address**      – ``address`` node attribute is identical
          (case-insensitive) on ≥ 2 nodes.
        * **Shared phone**        – ``phone`` node attribute appears on ≥ 2 nodes.

        Parameters
        ----------
        node_metadata:
            Optional mapping ``{gstin: {"bank_account": ..., "address": ...,
            "phone": ...}}`` to enrich node attributes before analysis.  When
            ``None``, only attributes already present on graph nodes are used
            (the risk score component is still computed from graph topology).

        Returns
        -------
        list[dict]
            One entry per flagged component with keys:
            ``component_id``, ``nodes``, ``size``, ``flags``, ``shared_attrs``,
            ``risk_level``.
        """
        G = graph if graph is not None else self._require_graph()

        # Optionally enrich node attributes from caller-supplied metadata
        if node_metadata:
            for gstin, meta in node_metadata.items():
                if gstin in G.nodes:
                    G.nodes[gstin].update(meta)

        flagged: list[dict] = []

        for comp_id, component in enumerate(
            nx.weakly_connected_components(G), start=1
        ):
            if len(component) < 2:
                continue

            shared: dict[str, list] = defaultdict(list)

            # Gather attribute buckets
            bank_acc_map:  dict[str, list[str]] = defaultdict(list)
            address_map:   dict[str, list[str]] = defaultdict(list)
            phone_map:     dict[str, list[str]] = defaultdict(list)

            for gstin in component:
                attrs = G.nodes[gstin]
                if ba := attrs.get("bank_account"):
                    bank_acc_map[str(ba)].append(gstin)
                if addr := attrs.get("address"):
                    address_map[str(addr).strip().lower()].append(gstin)
                if ph := attrs.get("phone"):
                    phone_map[str(ph)].append(gstin)

            flags: list[str] = []
            shared_details: dict[str, Any] = {}

            shared_banks = {k: v for k, v in bank_acc_map.items() if len(v) >= 2}
            if shared_banks:
                flags.append("SHARED_BANK_ACCOUNT")
                shared_details["shared_bank_accounts"] = shared_banks

            shared_addrs = {k: v for k, v in address_map.items() if len(v) >= 2}
            if shared_addrs:
                flags.append("SHARED_ADDRESS")
                shared_details["shared_addresses"] = shared_addrs

            shared_phones = {k: v for k, v in phone_map.items() if len(v) >= 2}
            if shared_phones:
                flags.append("SHARED_PHONE")
                shared_details["shared_phones"] = shared_phones

            # Also flag dense clusters where the majority of possible
            # directed edges are actually present (high edge density).
            n = len(component)
            sub = G.subgraph(component)
            max_edges = n * (n - 1)
            density = sub.number_of_edges() / max_edges if max_edges > 0 else 0.0
            if density > 0.5 and n >= 3:
                flags.append("HIGH_EDGE_DENSITY")
                shared_details["edge_density"] = round(density, 4)

            if not flags:
                continue

            risk_level = (
                "HIGH"   if len(flags) >= 2 else
                "MEDIUM" if flags else
                "LOW"
            )

            flagged.append({
                "component_id": comp_id,
                "nodes":        sorted(component),
                "size":         n,
                "flags":        flags,
                "shared_attrs": shared_details,
                "risk_level":   risk_level,
            })

        self._suspicious_clusters = flagged
        logger.info("Suspicious clusters: %d flagged", len(flagged))
        return flagged

    # ------------------------------------------------------------------
    # 4. Node risk scoring
    # ------------------------------------------------------------------

    def compute_node_risk_scores(
        self, graph: nx.DiGraph | None = None
    ) -> dict[str, float]:
        """
        Compute a 0–1 risk score for every node in *graph*.

        The score combines:

        * **PageRank** — measures structural centrality.  Nodes through which
          large volumes of transactions flow score higher.
        * **Circular-trading involvement** — nodes that appear in at least one
          ``CIRCULAR_TRADING`` cycle receive a +0.30 boost.
        * **Suspicious-cluster membership** — nodes in a ``HIGH`` risk cluster
          receive +0.20; ``MEDIUM`` +0.10.
        * **ITC imbalance proxy** — nodes whose ``net_gst_paid`` is strongly
          negative (large ITC claimant relative to outward liability) receive
          a proportional boost.

        All components are clipped to [0, 1] before being returned.

        Returns
        -------
        dict[str, float]
            ``{gstin: risk_score}``
        """
        G = graph if graph is not None else self._require_graph()

        # --- PageRank (use invoice_value as weight) -----------------------
        try:
            pr = nx.pagerank(G, weight="invoice_value", max_iter=200)
        except nx.PowerIterationFailedConvergence:
            pr = nx.pagerank(G, weight=None, max_iter=500)

        pr_values = list(pr.values())
        pr_max    = max(pr_values) if pr_values else 1.0
        pr_norm   = {g: v / pr_max for g, v in pr.items()}  # normalise to [0,1]

        # --- Circular-trading flag set ------------------------------------
        circ_nodes: set[str] = set()
        for cycle_info in self._circular_cycles:
            if cycle_info["flag"] == "CIRCULAR_TRADING":
                circ_nodes.update(cycle_info["cycle"])

        # --- Cluster risk map (gstin → bonus) ----------------------------
        cluster_bonus: dict[str, float] = {}
        for cluster in self._suspicious_clusters:
            bonus = 0.20 if cluster["risk_level"] == "HIGH" else 0.10
            for gstin in cluster["nodes"]:
                cluster_bonus[gstin] = max(cluster_bonus.get(gstin, 0.0), bonus)

        # --- ITC imbalance proxy -----------------------------------------
        # net_gst_paid < 0 means the node is a net ITC claimant.
        # We normalise the magnitude relative to the most extreme value.
        net_gst_vals = [
            abs(G.nodes[g].get("net_gst_paid", 0.0))
            for g in G.nodes
            if G.nodes[g].get("net_gst_paid", 0.0) < 0
        ]
        max_imbalance = max(net_gst_vals) if net_gst_vals else 1.0

        scores: dict[str, float] = {}
        for gstin in G.nodes:
            base      = pr_norm.get(gstin, 0.0)
            circ_add  = 0.30 if gstin in circ_nodes else 0.0
            clust_add = cluster_bonus.get(gstin, 0.0)

            net_gst = G.nodes[gstin].get("net_gst_paid", 0.0)
            itc_add = (
                0.20 * abs(net_gst) / max_imbalance
                if net_gst < 0 else 0.0
            )

            raw = base + circ_add + clust_add + itc_add
            scores[gstin] = round(min(raw, 1.0), 4)

        self._risk_scores = scores
        return scores

    def compute_node_risk_score(self, gstin: str) -> float:
        """
        Return the risk score for a single *gstin*.

        If :meth:`compute_node_risk_scores` has not been called yet, it is
        invoked automatically.
        """
        if not self._risk_scores:
            self.compute_node_risk_scores()
        return self._risk_scores.get(gstin, 0.0)

    # ------------------------------------------------------------------
    # 5. Visualisation
    # ------------------------------------------------------------------

    def visualize_graph(
        self,
        output_path: str | Path | None = None,
        graph: nx.DiGraph | None = None,
        max_nodes: int = 120,
    ) -> Path:
        """
        Save a graph visualisation highlighting fraud patterns.

        Colouring scheme:

        * **Red nodes / edges** – involved in a ``CIRCULAR_TRADING`` cycle.
        * **Orange nodes**      – in a suspicious cluster.
        * **Blue nodes**        – normal.
        * Edge width            – proportional to log₁₀(invoice_value).

        Parameters
        ----------
        output_path:
            File path for the saved image (PNG).  Defaults to
            ``outputs/gst_transaction_graph.png``.
        max_nodes:
            When the graph has more nodes than this, only the highest-PageRank
            nodes are shown (avoids an unreadable hairball).

        Returns
        -------
        Path
            Absolute path to the saved image.
        """
        import matplotlib
        matplotlib.use("Agg")   # non-interactive backend — safe in all envs
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches

        G = graph if graph is not None else self._require_graph()

        if not self._risk_scores:
            self.compute_node_risk_scores(G)

        output_path = Path(output_path) if output_path else (
            OUTPUT_DIR / "gst_transaction_graph.png"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # --- Sub-sample if too large -------------------------------------
        if G.number_of_nodes() > max_nodes:
            pr     = nx.pagerank(G, weight="invoice_value")
            top_nodes = sorted(pr, key=pr.get, reverse=True)[:max_nodes]
            G = G.subgraph(top_nodes).copy()
            logger.info("Visualising top-%d nodes by PageRank", max_nodes)

        circ_nodes: set[str] = set()
        circ_edges: set[tuple[str, str]] = set()
        for c in self._circular_cycles:
            if c["flag"] == "CIRCULAR_TRADING":
                circ_nodes.update(c["cycle"])
                n = len(c["cycle"])
                for i in range(n):
                    circ_edges.add(
                        (c["cycle"][i], c["cycle"][(i + 1) % n])
                    )

        cluster_nodes: set[str] = set()
        for cl in self._suspicious_clusters:
            if cl["risk_level"] in ("HIGH", "MEDIUM"):
                cluster_nodes.update(cl["nodes"])

        # --- Layout -------------------------------------------------------
        fig, ax = plt.subplots(figsize=(16, 12))
        try:
            pos = nx.kamada_kawai_layout(G, weight="invoice_value")
        except Exception:
            pos = nx.spring_layout(G, seed=42, k=1.5 / math.sqrt(G.number_of_nodes() + 1))

        # Node colours
        node_colors = []
        for g in G.nodes:
            if g in circ_nodes:
                node_colors.append("#e74c3c")      # red
            elif g in cluster_nodes:
                node_colors.append("#e67e22")      # orange
            else:
                node_colors.append("#3498db")      # blue

        # Node sizes (scaled by total_sales, capped)
        max_sales = max(
            (G.nodes[g].get("total_sales", 1) for g in G.nodes), default=1
        )
        node_sizes = [
            300 + 1200 * (G.nodes[g].get("total_sales", 0) / max(max_sales, 1))
            for g in G.nodes
        ]

        # Edge colours & widths
        edge_colors = []
        edge_widths = []
        for u, v in G.edges:
            edata = G.edges[u, v]
            val   = max(edata.get("invoice_value", 1), 1)
            widths = max(0.5, math.log10(val) - 3)   # 4 decimals → ~1px, 10M → ~4px
            edge_widths.append(widths)
            edge_colors.append(
                "#e74c3c" if (u, v) in circ_edges else "#aab7b8"
            )

        # Draw
        nx.draw_networkx_nodes(
            G, pos, ax=ax,
            node_color=node_colors,
            node_size=node_sizes,
            alpha=0.85,
        )
        nx.draw_networkx_edges(
            G, pos, ax=ax,
            edge_color=edge_colors,
            width=edge_widths,
            arrows=True,
            arrowsize=10,
            alpha=0.6,
            connectionstyle="arc3,rad=0.08",
        )

        # Label only high-risk nodes to avoid clutter
        high_risk_nodes = {
            g for g in G.nodes
            if g in circ_nodes or g in cluster_nodes
        }
        labels = {
            g: G.nodes[g].get("gstin", g)[:12] + "…"
            if len(G.nodes[g].get("gstin", g)) > 12 else G.nodes[g].get("gstin", g)
            for g in high_risk_nodes
        }
        nx.draw_networkx_labels(
            G, pos, labels=labels, ax=ax,
            font_size=6, font_color="#2c3e50",
        )

        # Legend
        legend_patches = [
            mpatches.Patch(color="#e74c3c", label="Circular trading node/edge"),
            mpatches.Patch(color="#e67e22", label="Suspicious cluster node"),
            mpatches.Patch(color="#3498db", label="Normal node"),
            mpatches.Patch(color="#aab7b8", label="Normal edge"),
        ]
        ax.legend(handles=legend_patches, loc="upper left", fontsize=9)

        n_circ = sum(1 for c in self._circular_cycles if c["flag"] == "CIRCULAR_TRADING")
        ax.set_title(
            f"GST Transaction Graph  |  "
            f"{G.number_of_nodes()} nodes · {G.number_of_edges()} edges  |  "
            f"{n_circ} circular pattern(s) detected",
            fontsize=12, pad=14,
        )
        ax.axis("off")
        plt.tight_layout()
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        logger.info("Graph visualisation saved to %s", output_path)
        return output_path

    # ------------------------------------------------------------------
    # 6. Convenience: full pipeline
    # ------------------------------------------------------------------

    def run_full_analysis(
        self,
        all_companies_gst_data: list[dict] | None = None,
        node_metadata: dict[str, dict] | None = None,
        visualize: bool = True,
        viz_output: str | Path | None = None,
    ) -> tuple[nx.DiGraph, dict[str, float]]:
        """
        Run the full pipeline: build → detect cycles → detect clusters → score.

        Parameters
        ----------
        all_companies_gst_data:
            Same as :meth:`build_graph`.  Pass ``None`` to load from the
            pre-built JSON file.
        node_metadata:
            Optional per-GSTIN metadata dict (bank_account, address, phone).
        visualize:
            Whether to save a PNG visualisation.
        viz_output:
            Output path for the visualisation (passed to :meth:`visualize_graph`).

        Returns
        -------
        (graph, risk_scores)
        """
        G      = self.build_graph(all_companies_gst_data)
        cycles = self.find_circular_patterns(G)
        clust  = self.find_suspicious_clusters(G, node_metadata)
        scores = self.compute_node_risk_scores(G)

        if visualize:
            self.visualize_graph(viz_output, G)

        return G, scores

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_graph(self) -> nx.DiGraph:
        if self.graph is None:
            raise RuntimeError(
                "Graph not built yet — call build_graph() first."
            )
        return self.graph

    def _load_from_graph_file(
        self,
    ) -> tuple[list[dict], dict[str, dict]]:
        """Load edges and nodes from the pre-built gst_transaction_graph.json."""
        path = self.gst_dir / "gst_transaction_graph.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Transaction graph file not found: {path}\n"
                "Run GSTDataGenerator first."
            )
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        edges_raw: list[dict] = raw.get("edges", [])

        nodes_raw: dict[str, dict] = {}
        for gstin, attrs in raw.get("nodes", {}).items():
            nodes_raw[gstin] = {
                "gstin":             gstin,
                "total_sales":       attrs.get("total_supplied", 0.0),
                "total_purchases":   attrs.get("total_purchased", 0.0),
                "net_gst_paid":      0.0,    # recomputed from edges
                "sector":            attrs.get("sector", "Unknown"),
                "registration_date": attrs.get("registration_date", None),
            }
        return edges_raw, nodes_raw

    @staticmethod
    def _edges_from_company_data(
        companies: list[dict[str, Any]],
    ) -> list[dict]:
        """Extract raw invoice edge dicts from company GSTR data."""
        edges: list[dict] = []
        for cd in companies:
            gstr1  = cd.get("gstr1",  {})
            gstr2a = cd.get("gstr2a", {})
            for inv in gstr1.get("invoices", []):
                edges.append(inv)
            for inv in gstr2a.get("auto_populated_invoices", []):
                edges.append(inv)
        return edges

    @staticmethod
    def _nodes_from_company_data(
        companies: list[dict[str, Any]],
    ) -> dict[str, dict]:
        """Extract node attribute stubs from company GSTR data."""
        nodes: dict[str, dict] = {}
        for cd in companies:
            gstin = cd.get("gstr3b", {}).get("gstin") or cd.get("gstr1", {}).get("gstin")
            if gstin and gstin not in nodes:
                nodes[gstin] = {
                    "gstin":             gstin,
                    "total_sales":       0.0,
                    "total_purchases":   0.0,
                    "net_gst_paid":      0.0,
                    "sector":            "Unknown",
                    "registration_date": None,
                }
        return nodes


# ---------------------------------------------------------------------------
# CLI smoke-test / standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    print("Building GST transaction graph from pre-generated data …")
    builder = TransactionGraphBuilder()

    G, risk_scores = builder.run_full_analysis(
        visualize=True,
        viz_output=OUTPUT_DIR / "gst_transaction_graph.png",
    )

    print(f"\nGraph summary:")
    print(f"  Nodes : {G.number_of_nodes()}")
    print(f"  Edges : {G.number_of_edges()}")

    print(f"\nCycle detection ({len(builder._circular_cycles)} total):")
    circ = [c for c in builder._circular_cycles if c["flag"] == "CIRCULAR_TRADING"]
    print(f"  CIRCULAR_TRADING : {len(circ)}")
    for c in circ[:5]:
        print(
            f"    len={c['cycle_length']}  value=₹{c['cycle_value']:,.0f}"
            f"  spread={c['value_spread_pct']:.1f}%"
            f"  nodes={c['cycle']}"
        )

    print(f"\nSuspicious clusters: {len(builder._suspicious_clusters)}")
    for cl in builder._suspicious_clusters[:5]:
        print(
            f"    id={cl['component_id']}  size={cl['size']}"
            f"  risk={cl['risk_level']}  flags={cl['flags']}"
        )

    top10 = sorted(risk_scores.items(), key=lambda x: -x[1])[:10]
    print(f"\nTop-10 highest-risk GSTINs:")
    for gstin, score in top10:
        print(f"  {gstin}  score={score:.4f}")

    print(f"\nVisualisation saved to: {OUTPUT_DIR / 'gst_transaction_graph.png'}")
    sys.exit(0)
