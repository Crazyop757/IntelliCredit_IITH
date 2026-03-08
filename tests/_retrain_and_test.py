import sys; sys.path.insert(0, 'src')
from scorer.credit_scorer import CreditScorer
import pandas as pd

cs = CreditScorer()
result = cs.train('data/silver/training_data.csv')
print('Train AUC:', round(result['auc'], 4))

_ALL_FEATURES = [
    'debt_to_equity', 'current_ratio', 'dscr', 'gst_health_score',
    'itc_gap_pct', 'circular_trading_confidence', 'litigation_count',
    'news_risk_score', 'has_wilful_default_flag', 'bounce_count',
    'revenue_growth_yoy', 'ebitda_margin', 'working_capital_days',
    'creditor_days', 'debtor_days', 'avg_monthly_balance_cr',
    'credit_utilization_pct', 'upi_concentration_pct', 'gst_filing_regularity',
    'turnover_consistency_score', 'promoter_pledging_pct', 'sector_npa_rate',
    'company_age_years', 'director_count',
]

def score(name, overrides):
    base = {k: 0.0 for k in _ALL_FEATURES}
    base.update(overrides)
    r = cs.score(pd.DataFrame([base]))
    band = r["risk_band"]
    pri = r["default_probability"]
    sc = r["risk_score"]
    print(f'\n{name} -> score={sc:.2f}  band={band}  prob={pri:.3f}')
    shap = r.get('shap_explanations') or {}
    all_sv = shap.get('all_shap_values') or {}
    for feat_name, val in sorted(all_sv.items(), key=lambda x: abs(x[1]), reverse=True)[:6]:
        direction = '+' if val > 0 else '-'
        print(f'  {direction} {feat_name:<36s} SHAP={val:+.4f}')

score('COMP_A (Clean)', {
    'debt_to_equity': 0.38, 'current_ratio': 1.85, 'dscr': 2.40,
    'gst_health_score': 9.77, 'itc_gap_pct': -3.89, 'circular_trading_confidence': 0.02,
    'litigation_count': 0, 'news_risk_score': 1.2, 'has_wilful_default_flag': 0, 'bounce_count': 0,
    'revenue_growth_yoy': 0.15, 'ebitda_margin': 0.22, 'working_capital_days': 45.0,
    'creditor_days': 35.0, 'debtor_days': 30.0, 'avg_monthly_balance_cr': 25.0,
    'credit_utilization_pct': 0.45, 'upi_concentration_pct': 0.20, 'gst_filing_regularity': 0.95,
    'turnover_consistency_score': 0.92, 'promoter_pledging_pct': 0.05, 'sector_npa_rate': 0.03,
    'company_age_years': 45.0, 'director_count': 10.0})

score('COMP_B (Medium)', {
    'debt_to_equity': 1.75, 'current_ratio': 1.18, 'dscr': 1.95,
    'gst_health_score': 9.63, 'itc_gap_pct': -6.17, 'circular_trading_confidence': 0.12,
    'litigation_count': 1, 'news_risk_score': 3.8, 'has_wilful_default_flag': 0, 'bounce_count': 2,
    'revenue_growth_yoy': 0.04, 'ebitda_margin': 0.10, 'working_capital_days': 95.0,
    'creditor_days': 65.0, 'debtor_days': 60.0, 'avg_monthly_balance_cr': 8.0,
    'credit_utilization_pct': 0.72, 'upi_concentration_pct': 0.50, 'gst_filing_regularity': 0.78,
    'turnover_consistency_score': 0.68, 'promoter_pledging_pct': 0.38, 'sector_npa_rate': 0.07,
    'company_age_years': 12.0, 'director_count': 5.0})

score('COMP_C (Fraud)', {
    'debt_to_equity': 2.80, 'current_ratio': 1.08, 'dscr': 1.82,
    'gst_health_score': 8.80, 'itc_gap_pct': 34.5, 'circular_trading_confidence': 0.82,
    'litigation_count': 2, 'news_risk_score': 7.2, 'has_wilful_default_flag': 0, 'bounce_count': 4,
    'revenue_growth_yoy': -0.15, 'ebitda_margin': 0.04, 'working_capital_days': 155.0,
    'creditor_days': 110.0, 'debtor_days': 95.0, 'avg_monthly_balance_cr': 0.8,
    'credit_utilization_pct': 0.94, 'upi_concentration_pct': 0.82, 'gst_filing_regularity': 0.55,
    'turnover_consistency_score': 0.35, 'promoter_pledging_pct': 0.72, 'sector_npa_rate': 0.14,
    'company_age_years': 3.0, 'director_count': 3.0})
