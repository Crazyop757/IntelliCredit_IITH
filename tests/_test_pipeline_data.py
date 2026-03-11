"""Quick test to verify pipeline data extraction works end-to-end."""
import requests, json, time

BASE = "http://127.0.0.1:8000/api/v1"
KEY = "dev-key-change-in-production"
H = {"X-API-Key": KEY}

data_dir = r"data\iith_testing"

with open(f"{data_dir}\\krishna_textile_annual_report.pdf", "rb") as f:
    pdf_bytes = f.read()
with open(f"{data_dir}\\krishna_textile_bank_statement.csv", "rb") as f:
    bank_bytes = f.read()

gst_files_list = []
for gst_file in ["krishna_gstr2a.json", "krishna_gstr3b.json"]:
    with open(f"{data_dir}\\{gst_file}", "rb") as f:
        gst_files_list.append(("gst_files", (gst_file, f.read(), "application/json")))

resp = requests.post(
    f"{BASE}/analysis/pipeline",
    headers=H,
    data={
        "company_name": "Krishna Textiles",
        "cin": "U17000TG2010PTC067890",
        "loan_amount_requested": "5000000",
        "loan_tenure_months": "36",
    },
    files=[
        ("pdf_file", ("krishna_textile_annual_report.pdf", pdf_bytes, "application/pdf")),
        ("bank_file", ("krishna_textile_bank_statement.csv", bank_bytes, "text/csv")),
    ] + gst_files_list,
)
print("Submit status:", resp.status_code)
job = resp.json()
print("Job:", json.dumps(job, indent=2))

job_id = job.get("job_id")
if not job_id:
    print("No job_id returned!")
    exit(1)

# Poll
for i in range(30):
    time.sleep(3)
    r = requests.get(f"{BASE}/analysis/jobs/{job_id}", headers=H)
    j = r.json()
    st = j.get("status")
    pct = j.get("progress_pct")
    stg = j.get("current_stage")
    print(f"Poll {i+1}: status={st} progress={pct}% stage={stg}")
    if st in ("DONE", "FAILED"):
        if st == "FAILED":
            print("FAILED:", j.get("error"))
        else:
            result = j.get("result", {})
            ingest = result.get("ingest", {})
            score = result.get("score", {})
            print()
            print("=== DATA AVAILABILITY ===")
            ef = ingest.get("extracted_financials", {})
            print(f"extracted_financials: {len(ef)} years")
            for yr, fy in ef.items():
                print(f"  {yr}: revenue={fy.get('revenue')}, ebitda={fy.get('ebitda')}, pat={fy.get('pat')}")
            bm = ingest.get("bank_metrics", {})
            print(f"bank_metrics.avg_monthly_balance: {bm.get('avg_monthly_balance')}")
            print(f"bank_metrics.total_annual_credits: {bm.get('total_annual_credits')}")
            print(f"bank_metrics.debit_credit_ratio: {bm.get('debit_credit_ratio')}")
            print(f"bank_metrics.bounce_count: {bm.get('bounce_count')}")
            print(f"bank_metrics.anomalies: {bm.get('anomalies')}")
            print(f"bank_metrics.cash_deposit_pct: {bm.get('cash_deposit_pct')}")
            gst = ingest.get("gst_reconciliation", {})
            print(f"gst.gst_health_score: {gst.get('gst_health_score')}")
            print(f"gst.itc_gap_pct: {gst.get('itc_gap_pct')}")
            print(f"gst.itc_claimed_3b: {gst.get('itc_claimed_3b')}")
            print(f"gst.itc_available_2a: {gst.get('itc_available_2a')}")
            print(f"gst.circular_trading_flag: {gst.get('circular_trading_flag')}")
            print(f"gst.gst_itc_fraud_risk: {gst.get('gst_itc_fraud_risk')}")
            print(f"gst.fictitious_vendor_count: {gst.get('fictitious_vendor_count')}")
            print(f"risk_score: {score.get('risk_score')}")
            print(f"risk_band: {score.get('risk_band')}")
            print(f"decision: {score.get('decision')}")
            rc = ingest.get("risk_clauses", [])
            print(f"risk_clauses: {len(rc)} clauses")
            if rc:
                print(f"  first: {rc[0]}")
            dirs = ingest.get("directors", [])
            print(f"directors: {len(dirs)}")
            if dirs:
                print(f"  first: {dirs[0]}")
            plog = result.get("_pipeline_log", [])
            print(f"pipeline_log:")
            for entry in plog:
                print(f"  {entry}")
            errs = result.get("_errors", [])
            if errs:
                print(f"ERRORS: {errs}")
        break
else:
    print("Timeout waiting for pipeline")
