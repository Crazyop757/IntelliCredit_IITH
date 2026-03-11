"""
create_placeholder_gnn.py
Generates a minimal GNN checkpoint so the app can start without training.
The checkpoint uses is_rule_based=True, meaning the detector falls back to
deterministic rule-based fraud scoring rather than random neural predictions.
Run automatically during Docker build (after pip install).
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

dest = _ROOT / "models" / "gnn_fraud_detector.pt"
dest.parent.mkdir(parents=True, exist_ok=True)

if dest.exists():
    print(f"GNN checkpoint already exists at {dest} — skipping.")
    sys.exit(0)

try:
    import torch
    from torch import nn

    try:
        from torch_geometric.nn import SAGEConv

        class _GraphSAGEFraudModel(nn.Module):
            def __init__(self, in_channels=8, hidden_channels=64, dropout=0.3):
                super().__init__()
                self.conv1      = SAGEConv(in_channels,     hidden_channels, aggr="mean")
                self.conv2      = SAGEConv(hidden_channels, hidden_channels, aggr="mean")
                self.dropout    = nn.Dropout(p=dropout)
                self.classifier = nn.Linear(hidden_channels, 1)

        model = _GraphSAGEFraudModel()
        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "model_config": {"in_channels": 8, "hidden_channels": 64, "dropout": 0.3},
                "node_index":    [],
                "is_rule_based": True,   # use deterministic rules, not random weights
            },
            dest,
        )
        print(f"GNN placeholder checkpoint saved → {dest}  (rule-based fallback mode)")
    except ImportError:
        # torch_geometric not available — save a rule-only stub (no model_state_dict needed)
        torch.save(
            {
                "model_config": {"in_channels": 8, "hidden_channels": 64, "dropout": 0.3},
                "node_index":    [],
                "is_rule_based": True,
            },
            dest,
        )
        print(f"GNN rule-only stub saved → {dest}  (torch_geometric unavailable)")
except ImportError:
    print("torch not available — GNN checkpoint not created (will show 'untrained' at startup)")
