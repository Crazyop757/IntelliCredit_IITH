from src.scorer.credit_scorer import CreditScorer

scorer = CreditScorer()
scorer.train("data/silver/training_data.csv")

# Test on a known high-risk company
test_features = {
    "debt_to_equity": 5.2,
    "current_ratio": 0.7,
    "dscr": 0.85,
    "gst_health_score": 2.1,
    "itc_gap_pct": 34.5,
    "circular_trading_confidence": 0.82,
    "litigation_count": 4,
    "news_risk_score": 7.8,
    "has_wilful_default_flag": 1,
    "bounce_count": 5,
}

result = scorer.score(test_features)
print("Risk Score:", result["risk_score"])
print("Risk Band:", result["risk_band"])
print("Default Probability:", result["default_probability"])
print("Top Risk Factors:")
for f in result["shap_explanations"]["top_risk_factors"]:
    print(f'  - {f["human_readable_name"]}: {f["shap_value"]:+.3f}')

# Expected: HIGH risk band, high default probability
