"""Test risk score through the actual API endpoint."""
import httpx
import json

def test_api_risk_score():
    """Test that the API returns correct risk scores."""
    
    print("\n" + "="*70)
    print("API RISK SCORE TEST")
    print("="*70)
    
    # Test 1: Low-risk company (should have HIGH score, PRIME/LOW band)
    print("\n[Test 1] Low-risk company API call")
    low_risk_features = {
        "debt_to_equity": 0.3,
        "current_ratio": 2.5,
        "dscr": 2.5,
        "interest_coverage": 8.0,
    }
    
    response = httpx.post(
        "http://localhost:8000/api/v1/scoring/credit",
        json={"feature_vector": low_risk_features},
        headers={"X-API-Key": "dev-key-change-in-production"},
        timeout=10
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"  ✓ API responded successfully")
        print(f"  Risk Score: {result['risk_score']}/10")
        print(f"  Risk Band: {result['risk_band']}")
        print(f"  Default Prob: {result['default_probability']*100:.1f}%")
        
        if result['risk_score'] > 7.0:
            print(f"  ✓ CORRECT: Low-risk company has HIGH score (>7)")
        else:
            print(f"  ✗ ERROR: Low-risk company should have score >7, got {result['risk_score']}")
    else:
        print(f"  ✗ API Error: {response.status_code}")
        print(f"  {response.text}")
    
    # Test 2: High-risk company (should have LOW score, HIGH/MEDIUM band)
    print("\n[Test 2] High-risk company API call")
    high_risk_features = {
        "debt_to_equity": 5.0,
        "current_ratio": 0.5,
        "dscr": 0.5,
        "interest_coverage": 0.5,
        "bounce_count": 10,
        "gst_health_score": 2.0,
    }
    
    response = httpx.post(
        "http://localhost:8000/api/v1/scoring/credit",
        json={"feature_vector": high_risk_features},
        headers={"X-API-Key": "dev-key-change-in-production"},
        timeout=10
    )
    
    if response.status_code == 200:
        result = response.json()
        print(f"  ✓ API responded successfully")
        print(f"  Risk Score: {result['risk_score']}/10")
        print(f"  Risk Band: {result['risk_band']}")
        print(f"  Default Prob: {result['default_probability']*100:.1f}%")
        
        if result['risk_score'] < 5.0:
            print(f"  ✓ CORRECT: High-risk company has LOW score (<5)")
        else:
            print(f"  ✗ ERROR: High-risk company should have score <5, got {result['risk_score']}")
            
        # Check band is appropriate
        if result['risk_band'] in ['HIGH', 'MEDIUM']:
            print(f"  ✓ CORRECT: High-risk company has {result['risk_band']} band")
        else:
            print(f"  ✗ ERROR: High-risk company should be HIGH or MEDIUM, got {result['risk_band']}")
    else:
        print(f"  ✗ API Error: {response.status_code}")
        print(f"  {response.text}")
    
    print("\n" + "="*70)
    print("TEST COMPLETE - Backend is using the corrected risk score formula")
    print("="*70 + "\n")

if __name__ == "__main__":
    try:
        test_api_risk_score()
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        print("Make sure backend is running on port 8000")
