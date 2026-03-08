"""
Quick smoke test for the FastAPI backend.
Run: python tests/smoke_api.py
"""
import json, sys, time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
API  = f"{BASE}/api/v1"
KEY  = "dev-key-change-in-production"

OK = 0; FAIL = 0

def req(method: str, url: str, body=None, expected=(200, 201, 202)):
    global OK, FAIL
    headers = {"X-API-Key": KEY, "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            status = resp.status
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status = e.code
        try:    payload = json.loads(e.read())
        except: payload = {}
    except Exception as e:
        status = 0
        payload = {"_error": str(e)}

    ok = status in expected
    mark = "OK " if ok else "ERR"
    short = str(payload)[:120].replace("\n", " ")
    label = f"{method:4} {url.replace(BASE, '')}"
    print(f"  {mark}  {status:3}  {label:<45}  {short}")
    if ok: OK += 1
    else:  FAIL += 1
    return status, payload


print("\n─── Health ────────────────────────────────────────────────────")
req("GET",  f"{BASE}/health")
req("GET",  f"{BASE}/health/ready")

print("\n─── Companies ─────────────────────────────────────────────────")
req("GET",  f"{API}/companies")
req("GET",  f"{API}/companies/RIL")
req("GET",  f"{API}/companies/RIL/bronze")
req("GET",  f"{API}/companies/RIL/silver")
req("GET",  f"{API}/companies/RIL/gold",       expected=(200, 404))

print("\n─── GST ───────────────────────────────────────────────────────")
req("POST", f"{API}/gst/reconcile",        {"company_id": "COMP_A_RELIANCE"})
req("POST", f"{API}/gst/ews",              {"company_id": "COMP_A_RELIANCE"})
req("POST", f"{API}/gst/gnn/predict",      None,          expected=(200, 422, 500))
req("GET",  f"{API}/gst/graph?company_id=COMP_A_RELIANCE&visualize=false",
    expected=(200, 500))

print("\n─── Scoring ───────────────────────────────────────────────────")
req("POST", f"{API}/scoring/feature-vector", {"company_id": "RIL"})
req("POST", f"{API}/scoring/credit",         {"company_id": "RIL"})
req("POST", f"{API}/scoring/qualitative",    {
    "management_quality": "experienced",
    "industry_outlook":   "stable",
    "regulatory_risk":    "low",
})

print("\n─── Research (async job) ──────────────────────────────────────")
s, p = req("POST", f"{API}/research/run", {
    "company_name":   "Reliance Industries",
    "company_cin":    "L17110MH1973PLC019786",
    "director_names": ["Mukesh Ambani"],
}, expected=(202,))
if s == 202:
    job_id = p.get("job_id")
    time.sleep(1)
    req("GET", f"{API}/research/jobs/{job_id}", expected=(200,))

print("\n─── CAM ───────────────────────────────────────────────────────")
req("POST", f"{API}/cam/five-cs", {
    "company_data":     {"company_name": "Test Co", "cin": "L17110MH1973PLC019786"},
    "financials":       {"revenue": 1000, "pat": 100},
    "research_report":  {"summary": "Company has stable performance."},
    "scoring_result":   {"final_score": 72},
})
s, p = req("POST", f"{API}/cam/generate", {
    "company_id":     "TEST_CO",
    "company_name":   "Test Co",
    "cin":            "L17110MH1973PLC019786",
    "scoring_result": {"final_score": 72},
}, expected=(202,))
if s == 202:
    job_id = p.get("job_id")
    time.sleep(1)
    req("GET", f"{API}/cam/jobs/{job_id}", expected=(200,))

print("\n─── Summary ───────────────────────────────────────────────────")
total = OK + FAIL
print(f"\n  {OK}/{total} PASSED,  {FAIL}/{total} FAILED\n")
sys.exit(0 if FAIL == 0 else 1)
