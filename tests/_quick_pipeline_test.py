"""Quick end-to-end pipeline test — submits bank+gst files, polls for result."""
import httpx, json, time, sys

API = "http://localhost:8000/api/v1"
HEADERS = {"X-API-Key": "dev-key-change-in-production"}


def run():
    # 1. Submit pipeline with bank CSV
    with open("data/raw/bank_statement_sample.csv", "rb") as f:
        bank_bytes = f.read()

    files = [("bank_file", ("bank_statement_sample.csv", bank_bytes, "text/csv"))]
    form = {
        "company_name": "Test Company Alpha 2024",
        "cin": "U12345MH2020PLC123456",
        "loan_amount_requested": "50",
        "loan_tenure_months": "60",
    }
    r = httpx.post(f"{API}/analysis/pipeline", data=form, files=files, headers=HEADERS, timeout=30)
    print(f"Submit: {r.status_code}")
    job = r.json()
    job_id = job["job_id"]
    print(f"Job ID: {job_id}")

    # 2. Poll
    for _ in range(90):
        time.sleep(3)
        r2 = httpx.get(f"{API}/analysis/jobs/{job_id}", headers=HEADERS, timeout=10)
        d = r2.json()
        pct = d.get("progress_pct", 0)
        stage = d.get("current_stage", "-")
        status = d["status"]
        print(f"  [{pct:3d}%] status={status}  stage={stage}")
        if status in ("DONE", "FAILED"):
            if status == "DONE":
                res = d.get("result", {})
                score = res.get("score", {})
                bank = res.get("ingest", {}).get("bank_metrics", {})
                print()
                print("=" * 50)
                print(f"risk_score          : {score.get('risk_score')}")
                print(f"risk_band           : {score.get('risk_band')}")
                print(f"default_probability : {score.get('default_probability')}")
                print(f"decision            : {score.get('decision')}")
                print(f"bounce_count        : {bank.get('bounce_count')}")
                print(f"avg_balance_cr      : {bank.get('avg_monthly_balance')}")
                print(f"errors in pipeline  : {res.get('errors', [])}")
            else:
                print(f"PIPELINE FAILED: {d.get('error')}")
            return

    print("Timed out waiting for pipeline")


if __name__ == "__main__":
    run()
