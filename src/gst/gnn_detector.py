"""
gnn_detector.py — GNN-based circular trading / ITC fraud detector.

Architecture overview
---------------------
* **GraphSAGEFraudModel** — 2-layer GraphSAGE (SAGEConv) network with 64 hidden
  dims, ReLU activations, and Dropout(0.3).  Outputs a per-node fraud
  probability in [0, 1] via a sigmoid head.

* **CircularTradingDetector** — orchestrates graph conversion, training,
  inference, model persistence, and rule-based fallback.

  1. ``convert_to_pyg_data(nx_graph)``   → (PyG Data, node_index)
  2. ``make_labels(node_index, fraud_gstins)`` → label tensor
  3. ``train_model(data, labels)``        → training history dict
  4. ``predict_fraud(graph)``             → {gstin: {fraud_probability, risk_flag}}
  5. ``save_model()`` / ``load_model()``  → models/gnn_fraud_detector.pt

Fallback
--------
When fewer than ``_MIN_FRAUD_SAMPLES`` (default 5) labelled fraud nodes are
present the system switches to the rule-based
:class:`~src.gst.graph_builder.TransactionGraphBuilder` detector and annotates
every result with ``"method": "rule_based"``.

Node features (8-D)
-------------------
0. total_sales_normalized
1. total_purchases_normalized
2. net_gst_liability_normalized
3. filing_regularity_score  (out-degree proxy)
4. is_recently_registered   (placeholder – 0 in synthetic data)
5. sector_encoded
6. state_encoded            (from GSTIN state prefix)
7. transaction_count_normalized

Edge features (3-D, stored in data.edge_attr)
---------------------------------------------
0. transaction_value_normalized
1. is_round_number
2. days_since_registration  (placeholder – 0 in synthetic data)

.. note::
    Standard ``SAGEConv`` does not consume edge features during message
    passing.  ``data.edge_attr`` is stored for downstream use (edge classifiers,
    custom message-passing layers, or explainability tooling).
"""

from __future__ import annotations

import json
import logging
import math
import sys
import warnings
from pathlib import Path
from typing import Any

# Ensure project root is importable when this file is run directly
_PROJECT_ROOT_INIT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT_INIT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_INIT))

import networkx as nx
import torch
import torch.nn as nn
import torch.nn.functional as F

try:
    from torch_geometric.data import Data  # type: ignore[import]
    from torch_geometric.nn import SAGEConv  # type: ignore[import]
    _PYG_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PYG_AVAILABLE = False
    warnings.warn(
        "torch_geometric is not installed — GNN detector disabled; "
        "rule-based fallback will be used.",
        stacklevel=2,
    )

logger = logging.getLogger("intelli_credit.gst.gnn_detector")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT       = Path(__file__).resolve().parents[2]
GST_RAW_DIR         = _PROJECT_ROOT / "data" / "raw" / "gst"
MODELS_DIR          = _PROJECT_ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)
_DEFAULT_MODEL_PATH = MODELS_DIR / "gnn_fraud_detector.pt"

# ---------------------------------------------------------------------------
# Hyper-parameters / thresholds
# ---------------------------------------------------------------------------
_MIN_FRAUD_SAMPLES   = 5      # fewer labelled fraud nodes → rule-based fallback
_FRAUD_THRESHOLD     = 0.70   # P ≥ 0.70 → HIGH_RISK
_MEDIUM_THRESHOLD    = 0.40   # P ≥ 0.40 → MEDIUM_RISK

# ---------------------------------------------------------------------------
# Sector vocabulary
# ---------------------------------------------------------------------------
_SECTOR_VOCAB: dict[str, int] = {
    "Unknown": 0, "Manufacturing": 1, "Trading": 2, "Services": 3,
    "Construction": 4, "IT": 5, "Healthcare": 6, "Finance": 7,
    "Agriculture": 8, "Other": 9,
}
_N_SECTORS = len(_SECTOR_VOCAB)


# ===========================================================================
# GraphSAGE fraud-classification model
# ===========================================================================

class GraphSAGEFraudModel(nn.Module):
    """
    2-layer GraphSAGE node classifier for binary fraud detection.

    Architecture::

        SAGEConv(in_channels → hidden) → ReLU → Dropout
        SAGEConv(hidden → hidden)      → ReLU → Dropout
        Linear(hidden → 1)             → Sigmoid

    Parameters
    ----------
    in_channels:
        Dimensionality of input node features (default 8).
    hidden_channels:
        Width of both hidden layers (default 64).
    dropout:
        Dropout probability applied after each SAGE layer (default 0.3).
    """

    def __init__(
        self,
        in_channels: int = 8,
        hidden_channels: int = 64,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()
        if not _PYG_AVAILABLE:
            raise ImportError(
                "torch_geometric must be installed to use GraphSAGEFraudModel."
            )
        self.conv1      = SAGEConv(in_channels,     hidden_channels, aggr="mean")
        self.conv2      = SAGEConv(hidden_channels, hidden_channels, aggr="mean")
        self.dropout    = nn.Dropout(p=dropout)
        self.classifier = nn.Linear(hidden_channels, 1)

    def forward(
        self, x: torch.Tensor, edge_index: torch.Tensor
    ) -> torch.Tensor:
        """
        Parameters
        ----------
        x:          Node feature matrix  [N, in_channels]
        edge_index: COO sparse edge index [2, E]

        Returns
        -------
        torch.Tensor [N, 1]  — fraud probability in (0, 1) per node
        """
        h = self.conv1(x, edge_index)
        h = F.relu(h)
        h = self.dropout(h)
        h = self.conv2(h, edge_index)
        h = F.relu(h)
        h = self.dropout(h)
        return torch.sigmoid(self.classifier(h))


# ===========================================================================
# CircularTradingDetector
# ===========================================================================

class CircularTradingDetector:
    """
    GNN-based circular trading / ITC fraud detector with rule-based fallback.

    Parameters
    ----------
    model_path:
        Where to save / load the trained model.
        Defaults to ``models/gnn_fraud_detector.pt``.
    hidden_channels:
        Hidden dimension for the GraphSAGE layers.
    dropout:
        Dropout probability.

    Example
    -------
    >>> detector = CircularTradingDetector()
    >>> data, idx = detector.convert_to_pyg_data(G)
    >>> labels    = detector.make_labels(idx, fraud_gstins)
    >>> history   = detector.train_model(data, labels)
    >>> results   = detector.predict_fraud(G)
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        hidden_channels: int = 64,
        dropout: float = 0.3,
    ) -> None:
        self.model_path      = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self.hidden_channels = hidden_channels
        self.dropout         = dropout
        self.model: GraphSAGEFraudModel | None = None
        self._node_index: list[str] = []
        self._is_rule_based: bool   = not _PYG_AVAILABLE

    # ------------------------------------------------------------------
    # 1. Graph → PyG Data
    # ------------------------------------------------------------------

    def convert_to_pyg_data(
        self,
        networkx_graph: nx.DiGraph,
    ) -> tuple["Data", list[str]]:
        """
        Convert a NetworkX DiGraph to a PyG ``Data`` object.

        Returns
        -------
        (data, node_index)
            ``node_index[i]`` is the GSTIN string corresponding to row *i*
            in ``data.x`` and position *i* in the label / prediction tensors.
        """
        if not _PYG_AVAILABLE:
            raise ImportError("torch_geometric is required.")

        G = networkx_graph
        nodes       = list(G.nodes())
        node_to_idx = {g: i for i, g in enumerate(nodes)}

        # ---- Raw values for normalisation --------------------------------
        sales_raw  = [float(G.nodes[g].get("total_sales",     0.0)) for g in nodes]
        purch_raw  = [float(G.nodes[g].get("total_purchases",  0.0)) for g in nodes]
        net_raw    = [float(G.nodes[g].get("net_gst_paid",     0.0)) for g in nodes]
        out_degs   = [float(G.out_degree(g))                          for g in nodes]

        tx_counts  = [
            float(sum(
                G.edges[g, nb].get("transaction_count", 1)
                for nb in G.successors(g)
            ))
            for g in nodes
        ]

        log_sales   = [math.log1p(v) for v in sales_raw]
        log_purch   = [math.log1p(v) for v in purch_raw]
        max_log_s   = max(log_sales)   or 1.0
        max_log_p   = max(log_purch)   or 1.0
        max_out_deg = max(out_degs)    or 1.0
        max_tx_cnt  = max(tx_counts)   or 1.0
        max_net_abs = max(abs(v) for v in net_raw) or 1.0

        # ---- Node feature matrix [N, 8] ----------------------------------
        x_rows: list[list[float]] = []
        for i, g in enumerate(nodes):
            x_rows.append([
                log_sales[i]  / max_log_s,                      # 0 total_sales_norm
                log_purch[i]  / max_log_p,                      # 1 total_purchases_norm
                net_raw[i]    / max_net_abs,                    # 2 net_gst_liability
                out_degs[i]   / max_out_deg,                    # 3 filing_regularity
                0.0,                                            # 4 is_recently_registered (placeholder)
                _sector_encode(G.nodes[g].get("sector", "Unknown")),  # 5 sector
                _state_encode(g),                               # 6 state from GSTIN
                tx_counts[i]  / max_tx_cnt,                    # 7 transaction_count_norm
            ])

        x = torch.tensor(x_rows, dtype=torch.float)

        # ---- Edge index [2, E] and features [E, 3] ----------------------
        all_edges = list(G.edges(data=True))
        if all_edges:
            inv_vals  = [float(ed.get("invoice_value", 0.0)) for _, _, ed in all_edges]
            log_ivs   = [math.log1p(v) for v in inv_vals]
            max_log_v = max(log_ivs) or 1.0

            src_list: list[int] = []
            dst_list: list[int] = []
            ef_rows:  list[list[float]] = []

            for (u, v, edata), inv_val, log_iv in zip(all_edges, inv_vals, log_ivs):
                if u not in node_to_idx or v not in node_to_idx:
                    continue
                src_list.append(node_to_idx[u])
                dst_list.append(node_to_idx[v])
                is_round = 1.0 if (inv_val > 0 and _is_round_number(inv_val)) else 0.0
                ef_rows.append([
                    log_iv / max_log_v,   # 0 transaction_value_norm
                    is_round,             # 1 is_round_number
                    0.0,                  # 2 days_since_registration (placeholder)
                ])

            edge_index = torch.tensor([src_list, dst_list], dtype=torch.long)
            edge_attr  = torch.tensor(ef_rows, dtype=torch.float)
        else:
            edge_index = torch.zeros((2, 0), dtype=torch.long)
            edge_attr  = torch.zeros((0, 3), dtype=torch.float)

        data = Data(x=x, edge_index=edge_index, edge_attr=edge_attr)
        self._node_index = nodes
        return data, nodes

    # ------------------------------------------------------------------
    # 2. Label construction
    # ------------------------------------------------------------------

    def make_labels(
        self,
        node_index: list[str],
        fraud_gstins: set[str],
    ) -> torch.Tensor:
        """
        Build a float label tensor aligned with *node_index*.

        Returns
        -------
        torch.Tensor  shape [N, 1], dtype float
            1.0 for fraud nodes, 0.0 for clean.
        """
        return torch.tensor(
            [[1.0] if g in fraud_gstins else [0.0] for g in node_index],
            dtype=torch.float,
        )

    # ------------------------------------------------------------------
    # 3. Training
    # ------------------------------------------------------------------

    def train_model(
        self,
        data: "Data",
        labels: torch.Tensor,
        train_mask: torch.Tensor | None = None,
        val_mask:   torch.Tensor | None = None,
        epochs: int = 100,
        lr: float = 0.01,
    ) -> dict[str, Any]:
        """
        Train the GraphSAGE classifier on labelled node data.

        Parameters
        ----------
        data:
            PyG ``Data`` object from :meth:`convert_to_pyg_data`.
        labels:
            Float tensor [N, 1] — 1.0 fraud, 0.0 clean.
        train_mask / val_mask:
            Optional boolean masks [N].  When ``None``, an 80/20 stratified
            split is created automatically.
        epochs:
            Training epochs (default 100).
        lr:
            Adam learning rate (default 0.01).

        Returns
        -------
        dict
            ``train_losses``, ``val_losses``, ``best_val_loss``, ``epochs``,
            ``used_fallback`` (False on success), ``model_path``.

        Notes
        -----
        * Weighted BCE handles class imbalance: fraud samples are up-weighted
          by ``n_clean / n_fraud``.
        * The checkpoint with the lowest validation loss is restored.
        * Falls back to rule-based mode when ``< _MIN_FRAUD_SAMPLES`` fraud
          labels are present.
        """
        if not _PYG_AVAILABLE:
            return self._fallback_result("torch_geometric not installed")

        n_fraud = int(labels.sum().item())
        n_total = labels.shape[0]
        n_clean = n_total - n_fraud

        if n_fraud < _MIN_FRAUD_SAMPLES:
            logger.warning(
                "Only %d fraud sample(s) found (minimum %d) — "
                "activating rule-based fallback.",
                n_fraud, _MIN_FRAUD_SAMPLES,
            )
            self._is_rule_based = True
            return self._fallback_result(
                f"Insufficient fraud samples ({n_fraud} < {_MIN_FRAUD_SAMPLES})"
            )

        print(
            f"\nTraining GraphSAGE fraud detector  "
            f"({n_fraud} fraud / {n_clean} clean nodes out of {n_total})"
        )

        # ---- Masks -------------------------------------------------------
        if train_mask is None or val_mask is None:
            train_mask, val_mask = _stratified_split(labels, seed=42)

        # ---- Weighted BCE for class imbalance ----------------------------
        pos_weight = torch.tensor([n_clean / n_fraud], dtype=torch.float)
        criterion  = nn.BCELoss(reduction="none")

        # ---- Model & optimiser -------------------------------------------
        self.model = GraphSAGEFraudModel(
            in_channels=data.x.shape[1],
            hidden_channels=self.hidden_channels,
            dropout=self.dropout,
        )
        optimizer = torch.optim.Adam(
            self.model.parameters(), lr=lr, weight_decay=1e-4
        )

        # ---- Training loop -----------------------------------------------
        train_losses: list[float] = []
        val_losses:   list[float] = []
        best_val_loss = float("inf")
        best_state: dict | None   = None

        for epoch in range(1, epochs + 1):
            # -- Train step
            self.model.train()
            optimizer.zero_grad()
            out       = self.model(data.x, data.edge_index)        # [N, 1]
            raw_loss  = criterion(out[train_mask], labels[train_mask])
            weights   = torch.where(
                labels[train_mask] > 0,
                pos_weight.expand_as(raw_loss),
                torch.ones_like(raw_loss),
            )
            train_loss = (raw_loss * weights).mean()
            train_loss.backward()
            optimizer.step()

            # -- Validation step
            self.model.eval()
            with torch.no_grad():
                out_val  = self.model(data.x, data.edge_index)
                raw_val  = criterion(out_val[val_mask], labels[val_mask])
                wts_v    = torch.where(
                    labels[val_mask] > 0,
                    pos_weight.expand_as(raw_val),
                    torch.ones_like(raw_val),
                )
                val_loss = (raw_val * wts_v).mean()

            tl = round(train_loss.item(), 4)
            vl = round(val_loss.item(),   4)
            train_losses.append(tl)
            val_losses.append(vl)

            if val_loss.item() < best_val_loss:
                best_val_loss = val_loss.item()
                best_state    = {
                    k: v.clone() for k, v in self.model.state_dict().items()
                }

            if epoch % 10 == 0:
                print(
                    f"  Epoch {epoch:3d}/{epochs}  "
                    f"train_loss={tl:.4f}  val_loss={vl:.4f}"
                )
                logger.info(
                    "Epoch %d/%d  train=%.4f  val=%.4f",
                    epoch, epochs, tl, vl,
                )

        # Restore best checkpoint
        if best_state is not None:
            self.model.load_state_dict(best_state)

        self._is_rule_based = False
        saved_path = self.save_model()
        logger.info("Training complete — best val_loss=%.4f", best_val_loss)

        return {
            "train_losses":  train_losses,
            "val_losses":    val_losses,
            "best_val_loss": round(best_val_loss, 4),
            "epochs":        epochs,
            "used_fallback": False,
            "model_path":    str(saved_path),
        }

    # ------------------------------------------------------------------
    # 4. Inference
    # ------------------------------------------------------------------

    def predict_fraud(
        self,
        graph: nx.DiGraph,
    ) -> dict[str, dict[str, Any]]:
        """
        Predict fraud probability for every node in *graph*.

        If the model has not been trained (or the fallback flag is set), the
        rule-based :class:`~src.gst.graph_builder.TransactionGraphBuilder`
        detector is used instead.

        Returns
        -------
        dict[str, dict]
            ``{gstin: {"fraud_probability": float,
                       "risk_flag": "HIGH_RISK" | "MEDIUM_RISK" | "LOW_RISK",
                       "method": "gnn" | "rule_based"}}``

        Risk thresholds
        ---------------
        * P ≥ 0.70 → ``HIGH_RISK``
        * P ≥ 0.40 → ``MEDIUM_RISK``
        * P <  0.40 → ``LOW_RISK``
        """
        if self._is_rule_based or self.model is None:
            return self._rule_based_predict(graph)

        data, node_index = self.convert_to_pyg_data(graph)
        self.model.eval()
        with torch.no_grad():
            probs = self.model(data.x, data.edge_index).squeeze(1)  # [N]

        return {
            gstin: {
                "fraud_probability": round(float(probs[i].item()), 4),
                "risk_flag":         _prob_to_flag(float(probs[i].item())),
                "method":            "gnn",
            }
            for i, gstin in enumerate(node_index)
        }

    # ------------------------------------------------------------------
    # 5. Model persistence
    # ------------------------------------------------------------------

    def save_model(self, path: str | Path | None = None) -> Path:
        """
        Save trained model weights + metadata to *path*.

        Returns
        -------
        Path  — absolute path where the file was written.
        """
        if self.model is None:
            raise RuntimeError("No trained model to save.")
        save_path = Path(path) if path else self.model_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "model_state_dict": self.model.state_dict(),
                "model_config": {
                    "in_channels":     8,
                    "hidden_channels": self.hidden_channels,
                    "dropout":         self.dropout,
                },
                "node_index":    self._node_index,
                "is_rule_based": self._is_rule_based,
            },
            save_path,
        )
        logger.info("Model saved → %s", save_path)
        return save_path

    def load_model(self, path: str | Path | None = None) -> None:
        """
        Load a previously saved model.

        Raises
        ------
        FileNotFoundError
            If the model file does not exist.
        """
        load_path = Path(path) if path else self.model_path
        if not load_path.exists():
            raise FileNotFoundError(f"Model file not found: {load_path}")
        ckpt               = torch.load(load_path, map_location="cpu", weights_only=True)
        cfg                = ckpt["model_config"]
        self.model         = GraphSAGEFraudModel(**cfg)
        self.model.load_state_dict(ckpt["model_state_dict"])
        self._node_index   = ckpt.get("node_index", [])
        self._is_rule_based = ckpt.get("is_rule_based", False)
        self.model.eval()
        logger.info("Model loaded ← %s", load_path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_result(reason: str) -> dict[str, Any]:
        return {
            "train_losses":    [],
            "val_losses":      [],
            "best_val_loss":   None,
            "epochs":          0,
            "used_fallback":   True,
            "fallback_reason": reason,
        }

    def _rule_based_predict(
        self, graph: nx.DiGraph
    ) -> dict[str, dict[str, Any]]:
        """Derive fraud probabilities from PageRank + anomaly flags."""
        from src.gst.graph_builder import TransactionGraphBuilder  # noqa: PLC0415

        builder         = TransactionGraphBuilder()
        builder.graph   = graph
        builder.find_circular_patterns(graph)
        builder.find_suspicious_clusters(graph)
        scores = builder.compute_node_risk_scores(graph)

        return {
            gstin: {
                "fraud_probability": round(score, 4),
                "risk_flag":         _prob_to_flag(score),
                "method":            "rule_based",
            }
            for gstin, score in scores.items()
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _sector_encode(sector: str) -> float:
    """Map sector name to a normalised float in [0, 1]."""
    idx = _SECTOR_VOCAB.get(sector, _SECTOR_VOCAB["Other"])
    return idx / (_N_SECTORS - 1)


def _state_encode(gstin: str) -> float:
    """
    Extract the 2-digit state code from a GSTIN and normalise to [0, 1].

    GST state codes run from 01 (Jammu & Kashmir) to 37 (Andaman & Nicobar);
    we normalise by 37.
    """
    try:
        state_code = int(gstin[:2])
        return min(state_code, 37) / 37.0
    except (ValueError, IndexError):
        return 0.0


def _is_round_number(value: float, multiples: tuple[int, ...] = (1000, 5000, 10000)) -> bool:
    """Return True when *value* is close to a multiple of any element in *multiples*."""
    for m in multiples:
        if abs(value % m) < 1e-2 or abs(value % m - m) < 1e-2:
            return True
    return False


def _prob_to_flag(p: float) -> str:
    if p >= _FRAUD_THRESHOLD:
        return "HIGH_RISK"
    if p >= _MEDIUM_THRESHOLD:
        return "MEDIUM_RISK"
    return "LOW_RISK"


def _stratified_split(
    labels: torch.Tensor,
    train_ratio: float = 0.80,
    seed: int = 42,
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Build stratified 80/20 train/val boolean masks.

    Guarantees at least 1 sample of each class in both splits when possible.
    """
    torch.manual_seed(seed)
    N          = labels.shape[0]
    flat       = labels.squeeze()
    fraud_idx  = (flat == 1).nonzero(as_tuple=True)[0]
    clean_idx  = (flat == 0).nonzero(as_tuple=True)[0]

    def split_indices(idx: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        perm   = idx[torch.randperm(idx.shape[0])]
        n_train = max(1, int(perm.shape[0] * train_ratio))
        return perm[:n_train], perm[n_train:]

    fraud_tr, fraud_v = split_indices(fraud_idx)
    clean_tr, clean_v = split_indices(clean_idx)

    train_mask = torch.zeros(N, dtype=torch.bool)
    val_mask   = torch.zeros(N, dtype=torch.bool)
    for idx in (fraud_tr, clean_tr):
        train_mask[idx] = True
    for idx in (fraud_v, clean_v):
        # If val split is empty (too few samples), reuse some training ones
        if idx.numel() > 0:
            val_mask[idx] = True

    # Ensure val_mask is non-empty
    if val_mask.sum() == 0:
        val_mask = train_mask.clone()

    return train_mask, val_mask


# ---------------------------------------------------------------------------
# Data-prep helper: extract fraud GSTINs from generated files
# ---------------------------------------------------------------------------

def collect_fraud_gstins(gst_dir: Path) -> set[str]:
    """
    Scan all ``*_gstr1.json`` and ``*_gstr3b.json`` files in *gst_dir* and
    return the set of GSTINs that are tagged with fraud signals:

    * GSTINs appearing on invoices with ``"circular_fraud": true`` in GSTR-1.
    * GSTINs listed in ``fictitious_itc_entries`` in GSTR-3B filings.
    * The company's own GSTIN when its GSTR-3B contains ``fraud_flags``.
    """
    fraud_gstins: set[str] = set()

    for gstr1_path in sorted(gst_dir.glob("*_gstr1.json")):
        with gstr1_path.open(encoding="utf-8") as fh:
            g1 = json.load(fh)
        for inv in g1.get("invoices", []):
            if inv.get("circular_fraud", False):
                fraud_gstins.add(inv["supplier_gstin"])
                fraud_gstins.add(inv["buyer_gstin"])

    for gstr3b_path in sorted(gst_dir.glob("*_gstr3b.json")):
        with gstr3b_path.open(encoding="utf-8") as fh:
            g3b = json.load(fh)
        for filing in g3b.get("filings", []):
            if filing.get("fraud_flags"):
                fraud_gstins.add(filing["gstin"])
            for entry in filing.get("fictitious_itc_entries", []):
                fraud_gstins.add(entry["supplier_gstin"])

    return fraud_gstins


# ---------------------------------------------------------------------------
# CLI smoke-test / standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    # ---- 1. Build graph --------------------------------------------------
    from src.gst.graph_builder import TransactionGraphBuilder  # noqa: PLC0415

    print("Step 1: Building transaction graph …")
    builder = TransactionGraphBuilder()
    G, _    = builder.run_full_analysis(visualize=False)
    print(f"  Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # ---- 2. Collect fraud GSTINs from synthetic data ---------------------
    print("\nStep 2: Collecting fraud labels from generated JSON files …")
    fraud_gstins = collect_fraud_gstins(GST_RAW_DIR)
    print(f"  Fraud GSTINs identified: {len(fraud_gstins)}")
    for g in sorted(fraud_gstins):
        print(f"    {g}")

    # ---- 3. Initialise detector & convert graph --------------------------
    print("\nStep 3: Converting graph to PyG format …")
    detector = CircularTradingDetector()
    data, node_index = detector.convert_to_pyg_data(G)
    print(
        f"  x: {data.x.shape}  "
        f"edge_index: {data.edge_index.shape}  "
        f"edge_attr: {data.edge_attr.shape}"
    )

    labels   = detector.make_labels(node_index, fraud_gstins)
    n_fraud  = int(labels.sum().item())
    n_clean  = labels.shape[0] - n_fraud
    print(f"  Labels: {n_fraud} fraud  /  {n_clean} clean")

    # ---- 4. Train --------------------------------------------------------
    print("\nStep 4: Training GraphSAGE model …")
    history = detector.train_model(data, labels, epochs=100, lr=0.01)

    if history["used_fallback"]:
        print(f"\n  [FALLBACK] {history['fallback_reason']}")
    else:
        print(
            f"\n  Training complete — best val_loss={history['best_val_loss']:.4f}"
            f"  model saved → {history['model_path']}"
        )

    # ---- 5. Inference ----------------------------------------------------
    print("\nStep 5: Running inference on full graph …")
    results = detector.predict_fraud(G)

    high_risk  = {g: r for g, r in results.items() if r["risk_flag"] == "HIGH_RISK"}
    medium_risk = {g: r for g, r in results.items() if r["risk_flag"] == "MEDIUM_RISK"}
    low_risk    = {g: r for g, r in results.items() if r["risk_flag"] == "LOW_RISK"}

    print(
        f"  HIGH_RISK={len(high_risk)}  "
        f"MEDIUM_RISK={len(medium_risk)}  "
        f"LOW_RISK={len(low_risk)}"
    )

    print("\n  Top-10 highest fraud-probability GSTINs:")
    for gstin, info in sorted(
        results.items(), key=lambda kv: -kv[1]["fraud_probability"]
    )[:10]:
        known = " ← known fraud" if gstin in fraud_gstins else ""
        print(
            f"    {gstin}  "
            f"P={info['fraud_probability']:.4f}  "
            f"[{info['risk_flag']}]  "
            f"method={info['method']}{known}"
        )

    sys.exit(0)
