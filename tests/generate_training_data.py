"""
generate_training_data.py
=========================
Generates a 2000-sample, 24-feature internally-coherent synthetic training
dataset at data/silver/training_data.csv.

Feature values are correlated WITHIN each risk band so every signal points
in the same direction — eliminating the contradictory patterns that caused
backwards SHAP signs.

  HIGH RISK  : 600 samples, label=1 (always)
  MEDIUM RISK: 800 samples, label=1/0 (45/55%)  — genuinely uncertain band
  LOW RISK   : 600 samples, label=0 (always)

Total: 2000 samples, ~50% default rate

Run from project root:
    python tests/generate_training_data.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
OUT = _ROOT / "data" / "silver" / "training_data.csv"


def make_sample(risk_level):
    """
    Generate one sample where ALL features are internally consistent
    with the risk level. No contradictory signals.
    """
    n = np.random.normal  # shorthand

    if risk_level == 'HIGH':
        s = {
            # Financial — all bad
            'debt_to_equity':               np.clip(n(5.5, 1.2), 3.5, 9.0),
            'current_ratio':                np.clip(n(0.65, 0.15), 0.3, 0.95),
            'dscr':                         np.clip(n(0.70, 0.15), 0.3, 0.95),
            'ebitda_margin':                np.clip(n(0.04, 0.02), 0.01, 0.09),
            'revenue_growth_yoy':           np.clip(n(-0.10, 0.08), -0.35, 0.05),
            'working_capital_days':         np.clip(n(140, 25), 90, 200),
            'debtor_days':                  np.clip(n(110, 20), 70, 160),
            'creditor_days':                np.clip(n(25, 8), 10, 45),

            # Bank — all stressed
            'avg_monthly_balance_cr':       np.clip(n(0.8, 0.4), 0.1, 2.0),
            'credit_utilization_pct':       np.clip(n(0.92, 0.05), 0.80, 0.99),
            'upi_concentration_pct':        np.clip(n(0.75, 0.10), 0.55, 0.95),
            'bounce_count':                 int(np.clip(n(7, 2), 3, 15)),

            # GST — all bad
            'gst_health_score':             np.clip(n(2.5, 0.8), 1.0, 4.0),
            'itc_gap_pct':                  np.clip(n(35, 8), 20, 55),
            'gst_filing_regularity':        np.clip(n(0.55, 0.12), 0.3, 0.75),
            'turnover_consistency_score':   np.clip(n(0.40, 0.10), 0.2, 0.60),
            'circular_trading_confidence':  np.clip(n(0.78, 0.12), 0.55, 0.98),

            # External — all bad
            'litigation_count':             int(np.clip(n(6, 2), 3, 12)),
            'news_risk_score':              np.clip(n(7.5, 1.2), 5.5, 10.0),
            'has_wilful_default_flag':      np.random.choice([0, 1], p=[0.25, 0.75]),
            'promoter_pledging_pct':        np.clip(n(0.68, 0.12), 0.45, 0.95),
            'sector_npa_rate':              np.clip(n(0.11, 0.02), 0.07, 0.15),
            'company_age_years':            np.clip(n(6, 3), 1, 15),
            'director_count':               int(np.clip(n(4, 1.5), 2, 8)),
        }
        label = 1

    elif risk_level == 'MEDIUM':
        s = {
            # Financial — mixed, some stress
            'debt_to_equity':               np.clip(n(2.5, 0.6), 1.5, 4.0),
            'current_ratio':                np.clip(n(1.10, 0.20), 0.80, 1.50),
            'dscr':                         np.clip(n(1.15, 0.20), 0.85, 1.50),
            'ebitda_margin':                np.clip(n(0.10, 0.04), 0.04, 0.18),
            'revenue_growth_yoy':           np.clip(n(0.05, 0.08), -0.10, 0.18),
            'working_capital_days':         np.clip(n(85, 20), 50, 130),
            'debtor_days':                  np.clip(n(70, 15), 45, 100),
            'creditor_days':                np.clip(n(45, 12), 25, 75),

            # Bank — slightly stressed
            'avg_monthly_balance_cr':       np.clip(n(4.0, 2.0), 1.0, 10.0),
            'credit_utilization_pct':       np.clip(n(0.72, 0.10), 0.55, 0.88),
            'upi_concentration_pct':        np.clip(n(0.50, 0.12), 0.30, 0.70),
            'bounce_count':                 int(np.clip(n(2, 1.2), 0, 5)),

            # GST — moderate
            'gst_health_score':             np.clip(n(5.0, 0.8), 3.5, 6.5),
            'itc_gap_pct':                  np.clip(n(14, 5), 5, 25),
            'gst_filing_regularity':        np.clip(n(0.75, 0.08), 0.60, 0.88),
            'turnover_consistency_score':   np.clip(n(0.65, 0.10), 0.45, 0.80),
            'circular_trading_confidence':  np.clip(n(0.30, 0.12), 0.10, 0.55),

            # External — some concerns
            'litigation_count':             int(np.clip(n(2, 1.2), 0, 5)),
            'news_risk_score':              np.clip(n(4.5, 1.2), 2.5, 7.0),
            'has_wilful_default_flag':      np.random.choice([0, 1], p=[0.88, 0.12]),
            'promoter_pledging_pct':        np.clip(n(0.32, 0.12), 0.10, 0.55),
            'sector_npa_rate':              np.clip(n(0.06, 0.02), 0.03, 0.10),
            'company_age_years':            np.clip(n(18, 8), 5, 40),
            'director_count':               int(np.clip(n(6, 2), 3, 10)),
        }
        # Medium risk is genuinely uncertain — 45% default rate
        label = np.random.choice([0, 1], p=[0.55, 0.45])

    else:  # LOW
        s = {
            # Financial — all strong
            'debt_to_equity':               np.clip(n(0.9, 0.4), 0.1, 1.8),
            'current_ratio':                np.clip(n(2.0, 0.4), 1.4, 3.5),
            'dscr':                         np.clip(n(2.2, 0.4), 1.5, 3.8),
            'ebitda_margin':                np.clip(n(0.20, 0.05), 0.12, 0.35),
            'revenue_growth_yoy':           np.clip(n(0.18, 0.07), 0.05, 0.38),
            'working_capital_days':         np.clip(n(45, 12), 20, 70),
            'debtor_days':                  np.clip(n(35, 10), 15, 55),
            'creditor_days':                np.clip(n(65, 15), 40, 95),

            # Bank — healthy
            'avg_monthly_balance_cr':       np.clip(n(18, 8), 8, 50),
            'credit_utilization_pct':       np.clip(n(0.42, 0.10), 0.20, 0.60),
            'upi_concentration_pct':        np.clip(n(0.28, 0.08), 0.10, 0.45),
            'bounce_count':                 int(np.clip(n(0.3, 0.5), 0, 2)),

            # GST — clean
            'gst_health_score':             np.clip(n(8.0, 0.8), 6.5, 10.0),
            'itc_gap_pct':                  np.clip(n(3, 2), 0, 8),
            'gst_filing_regularity':        np.clip(n(0.95, 0.04), 0.85, 1.0),
            'turnover_consistency_score':   np.clip(n(0.88, 0.06), 0.75, 1.0),
            'circular_trading_confidence':  np.clip(n(0.06, 0.04), 0.0, 0.18),

            # External — clean
            'litigation_count':             int(np.clip(n(0.3, 0.5), 0, 2)),
            'news_risk_score':              np.clip(n(1.8, 0.8), 0.2, 3.5),
            'has_wilful_default_flag':      0,
            'promoter_pledging_pct':        np.clip(n(0.08, 0.06), 0.0, 0.22),
            'sector_npa_rate':              np.clip(n(0.03, 0.01), 0.01, 0.06),
            'company_age_years':            np.clip(n(28, 10), 10, 60),
            'director_count':               int(np.clip(n(8, 2), 5, 15)),
        }
        label = 0

    return s, label


def main():
    """Generate 2000 samples with balanced classes and save to CSV."""
    np.random.seed(42)

    samples, labels = [], []

    for _ in range(600):   # HIGH RISK
        s, l = make_sample('HIGH')
        samples.append(s); labels.append(l)

    for _ in range(800):   # MEDIUM RISK (largest — hardest class)
        s, l = make_sample('MEDIUM')
        samples.append(s); labels.append(l)

    for _ in range(600):   # LOW RISK
        s, l = make_sample('LOW')
        samples.append(s); labels.append(l)

    df = pd.DataFrame(samples)
    df['label'] = labels

    # Shuffle
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(str(OUT), index=False)

    print(f"Total samples: {len(df)}")
    print(f"Default rate: {df.label.mean():.1%}")
    print(f"Feature correlations with label:")
    print(df.corr(numeric_only=True)['label'].sort_values().to_string())
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
