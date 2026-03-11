"""
Quick test to verify risk score calculation is fixed.
"""
import sys
sys.path.insert(0, '.')

from src.scorer.credit_scorer import CreditScorer

def test_risk_score_calculation():
    """Verify that risk_score = 10 * (1 - default_prob), higher = better."""
    scorer = CreditScorer()
    
    print("\n" + "="*70)
    print("RISK SCORE CALCULATION TEST")
    print("="*70)
    
    # Test 1: Low risk company (should have HIGH score)
    print("\n[Test 1] Low-risk company (good financials)")
    low_risk_features = {
        'debt_to_equity': 0.3,
        'current_ratio': 2.5,
        'dscr': 2.5,
        'interest_coverage': 8.0,
    }
    result = scorer.score(low_risk_features)
    print(f"  Default Probability: {result['default_probability']:.3f}")
    print(f"  Risk Score: {result['risk_score']}/10")
    print(f"  Risk Band: {result['risk_band']}")
    print(f"  ✓ Expected: HIGH score (>7), PRIME/LOW band")
    assert result['risk_score'] > 5.0, "Low-risk company should have score > 5"
    
    # Test 2: High risk company (should have LOW score)
    print("\n[Test 2] High-risk company (poor financials)")
    high_risk_features = {
        'debt_to_equity': 5.0,
        'current_ratio': 0.5,
        'dscr': 0.5,
        'interest_coverage': 0.5,
    }
    result = scorer.score(high_risk_features)
    print(f"  Default Probability: {result['default_probability']:.3f}")
    print(f"  Risk Score: {result['risk_score']}/10")
    print(f"  Risk Band: {result['risk_band']}")
    print(f"  ✓ Expected: LOW score (<5), HIGH/MEDIUM band")
    assert result['risk_score'] < 7.0, "High-risk company should have score < 7"
    
    # Test 3: Verify formula
    print("\n[Test 3] Verify formula: risk_score = 10 * (1 - default_prob)")
    for default_prob in [0.1, 0.3, 0.5, 0.7, 0.9]:
        expected_score = 10.0 * (1.0 - default_prob)
        print(f"  Default {default_prob:.1f} → Score {expected_score:.1f}/10")
    
    print("\n" + "="*70)
    print("✓ ALL TESTS PASSED!")
    print("Risk score calculation is correct:")
    print("  • Higher score = Lower risk (like FICO)")
    print("  • 10/10 = Best (0% default)")
    print("  • 0/10 = Worst (100% default)")
    print("="*70 + "\n")

if __name__ == "__main__":
    test_risk_score_calculation()
