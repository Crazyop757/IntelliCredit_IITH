"""Quick check: run pipeline and inspect graph data."""
import httpx, time, os

BASE = "http://127.0.0.1:8000/api/v1"
HEADERS = {"X-API-Key": "dev-key-change-in-production"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "iith_testing")
# Find the PDF
pdf_candidates = [
    os.path.join(ROOT, "scripts", "krishna_textiles_annual_report.pdf"),
    os.path.join(ROOT, "data", "iith_testing", "krishna_textiles_annual_report.pdf"),
    os.path.join(ROOT, "outputs", "krishna_textiles_annual_report.pdf"),
]
pdf_path = None
for p in pdf_candidates:
    if os.path.exists(p):
        pdf_path = p
        break
if not pdf_path:
    # Just use any PDF in the project
    for dirpath, _, fnames in os.walk(ROOT):
        for f in fnames:
            if f.endswith(".pdf"):
                pdf_path = os.path.join(dirpath, f)
                break
        if pdf_path:
            break

if not pdf_path:
    print("ERROR: No PDF found")
    exit(1)

print(f"Using PDF: {pdf_path}")
gst2a = os.path.join(DATA, "krishna_gstr2a.json")
gst3b = os.path.join(DATA, "krishna_gstr3b.json")
bank = os.path.join(DATA, "krishna_textile_bank_statement.csv")

files = [
    ("pdf_file", ("report.pdf", open(pdf_path, "rb"), "application/pdf")),
    ("bank_file", ("bank.csv", open(bank, "rb"), "text/csv")),
    ("gst_files", ("gstr2a.json", open(gst2a, "rb"), "application/json")),
    ("gst_files", ("gstr3b.json", open(gst3b, "rb"), "application/json")),
]

r = httpx.post(
    f"{BASE}/analysis/pipeline",
    headers=HEADERS,
    files=files,
    data={"company_name": "Krishna Textiles", "fiscal_year": "2024"},
    timeout=30,
)
job = r.json().get("data", r.json())
job_id = job["job_id"]
print(f"Job: {job_id}")

for i in range(60):
    time.sleep(3)
    r = httpx.get(f"{BASE}/analysis/jobs/{job_id}", headers=HEADERS, timeout=10)
    rd = r.json().get("data", r.json())
    status = rd["status"]
    if status == "DONE":
        print(f"  DONE after {(i+1)*3}s")
        result = rd["result"]
        gst = result.get("ingest", {}).get("gst_reconciliation", {})
        print(f"\ngraph_nodes: {len(gst.get('graph_nodes', []))}")
        print(f"graph_edges: {len(gst.get('graph_edges', []))}")
        print(f"circular_patterns: {len(gst.get('circular_patterns', []))}")
        print(f"circular_trading_flag: {gst.get('circular_trading_flag')}")
        print()
        for n in gst.get("graph_nodes", []):
            nm = n.get("name", "?")[:25]
            nid = n.get("id", "?")[:25]
            print(f"  Node: id={nid:25s}  name={nm:25s}  "
                  f"sales={n.get('total_sales',0):>12,.0f}  "
                  f"purch={n.get('total_purchases',0):>12,.0f}  "
                  f"circ={n.get('is_circular')}  "
                  f"risk={n.get('risk_score')}")
        print()
        for e in gst.get("graph_edges", []):
            src = str(e.get("source", ""))[:20]
            tgt = str(e.get("target", ""))[:20]
            print(f"  Edge: {src:20s} -> {tgt:20s}  "
                  f"val={e.get('invoice_value',0):>12,.0f}  "
                  f"circ={e.get('is_circular')}")
        print()
        for p in gst.get("circular_patterns", []):
            print(f"  Pattern: {p.get('flag')}  len={p.get('cycle_length')}  "
                  f"val={p.get('cycle_value',0):,.0f}  cycle={p.get('cycle')}")
        break
    elif status == "FAILED":
        print("FAILED:", rd.get("error"))
        break
    else:
        print(f"  Poll {i+1}: {status} ({rd.get('progress_pct',0)}%)")
