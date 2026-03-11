"""
Ingest service — orchestrates PDF, bank, and GST ingestion into the delta layers.
All heavy I/O and ML calls happen synchronously here (run via ThreadPoolExecutor
from the async routers).
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _company_id_from_name(name: str) -> str:
    """Derive a filesystem-safe company_id from a human name."""
    slug = re.sub(r"[^a-zA-Z0-9]", "_", name).upper()
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:40]


def _detect_gst_type(data: dict) -> str:
    """Detect GSTR type from JSON content."""
    form = data.get("form", "") or ""
    return_type = (data.get("return_type", "") or "").upper()

    # Check explicit type fields first
    if return_type in ("GSTR1", "GSTR-1") or form == "GSTR-1":
        return "gstr1"
    if return_type in ("GSTR2A", "GSTR-2A") or form == "GSTR-2A":
        return "gstr2a"
    if return_type in ("GSTR3B", "GSTR-3B") or form == "GSTR-3B":
        return "gstr3b"

    # Fallback: detect by characteristic keys
    if "invoices" in data or "b2b_invoices" in data:
        return "gstr1"
    if "auto_populated_invoices" in data or "inward_supplies" in data or "auto_populated_credits" in data:
        return "gstr2a"
    if "filings" in data or "monthly_data" in data or "monthly_filings" in data:
        return "gstr3b"
    return "unknown"


# ── PDF Ingestion ─────────────────────────────────────────────────────────────

def ingest_pdf(
    pdf_bytes: bytes,
    company_name: str,
    company_id: str,
    fiscal_year: int | None,
    persist: bool,
    file_name: str = "upload.pdf",
) -> dict[str, Any]:
    """
    Parse PDF → extract financials + NER → optionally write Delta layers.
    Returns a dict matching PDFIngestResponse fields.
    """
    from src.ingestor.pdf_parser import PDFParser
    from src.ingestor.financial_extractor import FinancialExtractor
    from src.ingestor.ner_extractor import NERExtractor

    # Write bytes to a temp file (parsers expect a path)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        parser = PDFParser()
        pdf_result = parser.parse(tmp_path)
        raw_text: str = pdf_result.get("raw_text", "")
        tables: list = pdf_result.get("tables", [])
        doc_type: str = pdf_result.get("doc_type", "UNKNOWN")
        pages: int = pdf_result.get("pages_processed", 0)

        extractor = FinancialExtractor()
        fin_result = extractor.extract(raw_text, tables, doc_type)
        figures = fin_result.get("figures", {})
        ratios = fin_result.get("ratios", {})
        directors_raw = fin_result.get("directors", [])
        risk_clauses_raw = fin_result.get("risk_clauses", [])

        # NER (may be heavy — catch failures gracefully)
        ner_result: dict = {}
        try:
            ner = NERExtractor()
            ner_result = ner.analyze(raw_text[:8000])  # cap at 8k chars to keep it fast
        except Exception as exc:
            log.warning("NER failed: %s", exc)

        # Persist to Delta Lake if requested
        bronze_id = None
        quality_flag = None
        if persist:
            try:
                from src.ingestor.delta_writer import DeltaWriter
                import datetime
                fy = fiscal_year or datetime.date.today().year
                writer = DeltaWriter()
                ids = writer.write(
                    pdf_result,
                    fin_result,
                    ner_result or None,
                    company_id=company_id,
                    file_name=file_name,
                    fiscal_year=fy,
                )
                bronze_id = ids.get("bronze_id")
                quality_flag = ids.get("quality_flag")
            except Exception as exc:
                log.warning("Delta write failed: %s", exc)

        # Parse risk clauses to dicts
        def _rc(rc) -> dict:
            if hasattr(rc, "__dict__"):
                return rc.__dict__
            return rc if isinstance(rc, dict) else {}

        return {
            "company_id": company_id,
            "company_name": company_name,
            "doc_type": doc_type,
            "pages_processed": pages,
            "fiscal_year": fiscal_year,
            "figures": figures,
            "ratios": ratios,
            "directors": directors_raw,
            "risk_clauses": [_rc(r) for r in risk_clauses_raw],
            "sentiment": (ner_result.get("sentiment") if ner_result else None),
            "auditor_sentiment": (ner_result.get("auditor_sentiment") if ner_result else None),
            "entities": (ner_result.get("entities") if ner_result else None),
            "bronze_id": bronze_id,
            "quality_flag": quality_flag,
        }
    finally:
        os.unlink(tmp_path)


# ── Bank Ingestion ────────────────────────────────────────────────────────────

def ingest_bank(
    csv_bytes: bytes,
    company_id: str,
    file_name: str = "bank.csv",
) -> dict[str, Any]:
    """
    Analyse bank statement CSV/Excel.
    Returns a dict matching BankIngestResponse fields.
    """
    from src.ingestor.bank_analyzer import BankStatementAnalyzer

    suffix = Path(file_name).suffix or ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(csv_bytes)
        tmp_path = Path(tmp.name)

    try:
        analyzer = BankStatementAnalyzer()
        result = analyzer.analyze(tmp_path)

        metrics = result.get("metrics", result)  # some versions return nested
        avg_bal_inr = metrics.get("average_monthly_balance", 0) or 0
        avg_bal_cr = round(avg_bal_inr / 1e7, 4) if avg_bal_inr else None

        total_credits_inr = metrics.get("total_annual_credits", 0) or 0
        total_credits_cr = round(total_credits_inr / 1e7, 4) if total_credits_inr else None

        anomalies = result.get("anomalies", {})
        anomaly_list = []
        if isinstance(anomalies, dict):
            for k, v in anomalies.items():
                if v:
                    anomaly_list.append({"type": str(k), "detail": str(v)})
        elif isinstance(anomalies, list):
            anomaly_list = [a if isinstance(a, dict) else {"detail": str(a)} for a in anomalies]

        row_count = int(metrics.get("transaction_count", 0) or 0)

        return {
            "company_id": company_id,
            "avg_monthly_balance_cr": avg_bal_cr,
            "debit_credit_ratio": metrics.get("debit_credit_ratio"),
            "bounce_count": int(metrics.get("bounce_count", 0) or 0),
            "upi_concentration": metrics.get("upi_percentage") or metrics.get("upi_concentration"),
            "cash_deposit_concentration": metrics.get("cash_deposit_concentration"),
            "total_annual_credits_cr": total_credits_cr,
            "anomalies": anomaly_list,
            "monthly_breakdown": metrics.get("monthly_breakdown"),
            "row_count": row_count,
        }
    finally:
        os.unlink(tmp_path)


# ── GST Ingestion ─────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _month_label_to_period(label: str) -> str:
    """Convert 'Apr-2023', 'Apr-23', or '2023-04' to 'YYYY-MM' format."""
    label = label.strip()
    if re.match(r"^\d{4}-\d{2}$", label):
        return label
    parts = re.split(r"[-/\s]", label)
    if len(parts) == 2:
        month_str, year_str = parts[0], parts[1]
        if month_str.isdigit():
            month_str, year_str = year_str, month_str
        mm = _MONTH_MAP.get(month_str[:3].lower())
        if mm and year_str.isdigit():
            # Handle 2-digit years: 23 → 2023, 99 → 1999
            if len(year_str) == 2:
                century = "20" if int(year_str) < 50 else "19"
                year_str = century + year_str
            return f"{year_str}-{mm}"
    return label


def _normalize_gst_data(data: dict, gst_type: str) -> dict:
    """Normalize alternate GST JSON formats to the reconciler's expected format."""
    # If already in the reconciler's format, return as-is
    if gst_type == "gstr2a" and "auto_populated_invoices" in data:
        return data
    if gst_type == "gstr3b" and "filings" in data:
        return data
    if gst_type == "gstr1" and "invoices" in data:
        return data

    normalized = dict(data)

    if gst_type == "gstr2a" and "inward_supplies" in data:
        # Convert inward_supplies → auto_populated_invoices
        invoices = []
        for supply in data["inward_supplies"]:
            total_itc = supply.get("total_itc_available", 0)
            months = max(supply.get("months_filed", 1), 1)
            monthly_itc = round(total_itc / months, 2)
            monthly_taxable = round(supply.get("total_taxable_value", 0) / months, 2)
            gstin = supply.get("supplier_gstin", "")
            # Distribute across months
            for i in range(months):
                month_num = (3 + i) % 12 + 1  # Apr=4 onwards
                year = int(data.get("financial_year", "2023-24")[:4])
                if month_num < 4:
                    year += 1
                period = f"{year}-{month_num:02d}"
                invoices.append({
                    "period": period,
                    "supplier_gstin": gstin,
                    "supplier_name": supply.get("supplier_name", ""),
                    "taxable_value": monthly_taxable,
                    "igst": 0.0,
                    "cgst": round(monthly_itc / 2, 2),
                    "sgst": round(monthly_itc / 2, 2),
                })
        normalized["auto_populated_invoices"] = invoices

    elif gst_type == "gstr2a" and "auto_populated_credits" in data:
        # Convert auto_populated_credits → auto_populated_invoices
        invoices = []
        for entry in data["auto_populated_credits"]:
            invoices.append({
                "period": _month_label_to_period(entry.get("month", "")),
                "supplier_gstin": entry.get("supplier_gstin", ""),
                "supplier_name": entry.get("supplier_name", ""),
                "taxable_value": entry.get("taxable_value", 0),
                "igst": entry.get("igst_available", entry.get("igst", 0)),
                "cgst": entry.get("cgst_available", entry.get("cgst", 0)),
                "sgst": entry.get("sgst_available", entry.get("sgst", 0)),
            })
        normalized["auto_populated_invoices"] = invoices

    elif gst_type == "gstr3b" and "monthly_data" in data:
        # Convert monthly_data → filings
        filings = []
        for entry in data["monthly_data"]:
            period = _month_label_to_period(entry.get("month", ""))
            filings.append({
                "period": period,
                "turnover": entry.get("taxable_turnover", 0),
                "itc_claimed": entry.get("itc_claimed", 0),
                "tax_paid": {
                    "cgst": entry.get("tax_paid_cgst", 0),
                    "sgst": entry.get("tax_paid_sgst", 0),
                },
                "filing_date": entry.get("filing_date"),
            })
        normalized["filings"] = filings
        normalized["gstin"] = data.get("gstin", "")

    elif gst_type == "gstr3b" and "monthly_filings" in data:
        # Convert monthly_filings → filings
        filings = []
        for entry in data["monthly_filings"]:
            period = _month_label_to_period(entry.get("month", ""))
            outward = entry.get("outward_supplies", {})
            itc = entry.get("itc_claimed", {})
            itc_total = itc.get("total", 0) if isinstance(itc, dict) else itc
            filings.append({
                "period": period,
                "turnover": outward.get("taxable_value", 0),
                "itc_claimed": itc_total,
                "tax_paid": {
                    "cgst": outward.get("cgst", 0),
                    "sgst": outward.get("sgst", 0),
                },
                "filing_date": entry.get("filing_date"),
            })
        normalized["filings"] = filings
        normalized["gstin"] = data.get("gstin", "")

    elif gst_type == "gstr1" and "b2b_invoices" in data:
        # Convert b2b_invoices (buyer_gstin) → invoices (receiver_gstin)
        invoices = []
        for inv in data["b2b_invoices"]:
            invoices.append({
                "period": _month_label_to_period(inv.get("month", "")),
                "taxable_value": inv.get("taxable_value", 0),
                "invoice_number": inv.get("invoice_no", ""),
                "receiver_gstin": inv.get("buyer_gstin", ""),
                "receiver_name": inv.get("buyer_name", ""),
            })
        normalized["invoices"] = invoices

    return normalized


def _synthesize_gstr1_from_3b(data_3b: dict) -> dict:
    """Generate a synthetic GSTR-1 from GSTR-3B monthly data for turnover reconciliation."""
    invoices = []
    monthly_data = data_3b.get("monthly_data", [])
    filings = data_3b.get("filings", [])

    source = monthly_data or filings
    for entry in source:
        if "month" in entry:
            period = _month_label_to_period(entry["month"])
            turnover = entry.get("taxable_turnover", 0)
        else:
            period = entry.get("period", "")
            turnover = entry.get("turnover", 0)

        if turnover:
            invoices.append({
                "period": period,
                "taxable_value": turnover,
                "invoice_number": f"SYN-{period}",
                "receiver_gstin": "SYNTHETIC",
            })

    return {
        "gstin": data_3b.get("gstin", ""),
        "invoices": invoices,
        "form": "GSTR-1",
    }


def _build_gst_graph(
    raw_data: dict[str, dict],
    company_id: str,
    reconciliation_report: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Build a transaction graph from normalised GST data and detect circular patterns.

    Returns (nodes, edges, circular_patterns) — all JSON-serialisable.
    """
    import networkx as nx

    G = nx.DiGraph()

    company_gstin = (
        raw_data.get("gstr3b", {}).get("gstin")
        or raw_data.get("gstr2a", {}).get("gstin")
        or raw_data.get("gstr1", {}).get("gstin")
        or f"{company_id}_GSTIN"
    )

    # Add the central company node
    G.add_node(company_gstin, name=company_id, role="company")

    # ── Supplier nodes+edges from GSTR-2A (inward supplies) ───────────
    gstr2a = raw_data.get("gstr2a", {})
    inward = gstr2a.get("inward_supplies", [])
    auto_pop = gstr2a.get("auto_populated_invoices", [])

    if inward:
        # Non-normalised format with supplier-level aggregates
        for supply in inward:
            sup_gstin = supply.get("supplier_gstin", "")
            if not sup_gstin:
                continue
            sup_name = supply.get("supplier_name", sup_gstin[:15])
            total_val = supply.get("total_taxable_value", 0)
            total_itc = supply.get("total_itc_available", 0)
            G.add_node(sup_gstin, name=sup_name, role="supplier",
                       total_sales=total_val, total_purchases=0.0)
            G.add_edge(sup_gstin, company_gstin,
                       invoice_value=total_val, tax_amount=total_itc,
                       transaction_count=supply.get("months_filed", 1))
    elif auto_pop:
        # Normalised per-month entries — aggregate by supplier
        from collections import defaultdict
        sup_agg: dict[str, dict] = defaultdict(lambda: {
            "value": 0.0, "tax": 0.0, "count": 0, "name": ""
        })
        for inv in auto_pop:
            gstin = inv.get("supplier_gstin", "")
            if not gstin:
                continue
            agg = sup_agg[gstin]
            agg["value"] += inv.get("taxable_value", 0)
            agg["tax"] += inv.get("igst", 0) + inv.get("cgst", 0) + inv.get("sgst", 0)
            agg["count"] += 1
            agg["name"] = inv.get("supplier_name", gstin[:15])
        for gstin, agg in sup_agg.items():
            G.add_node(gstin, name=agg["name"], role="supplier",
                       total_sales=agg["value"], total_purchases=0.0)
            G.add_edge(gstin, company_gstin,
                       invoice_value=agg["value"], tax_amount=agg["tax"],
                       transaction_count=agg["count"])

    # ── Customer nodes+edges from GSTR-1 (outward supplies) ──────────
    gstr1 = raw_data.get("gstr1", {})
    for inv in gstr1.get("invoices", []):
        recv = inv.get("receiver_gstin", "")
        if not recv or recv == "SYNTHETIC":
            # Create a generic "Customers" node for synthetic GSTR-1
            recv = "CUSTOMERS_AGGREGATE"
        val = inv.get("taxable_value", 0)
        recv_name = inv.get("receiver_name", "") or recv[:15]
        if not G.has_node(recv):
            G.add_node(recv, name=recv_name, role="customer",
                       total_sales=0.0, total_purchases=0.0)
        if G.has_edge(company_gstin, recv):
            ed = G.edges[company_gstin, recv]
            ed["invoice_value"] += val
            ed["transaction_count"] += 1
        else:
            G.add_edge(company_gstin, recv,
                       invoice_value=val, tax_amount=val * 0.18,
                       transaction_count=1)

    # ── Check for circular patterns: supplier→company AND company→supplier
    # This means money flows in a cycle (potential circular trading).
    circular_patterns: list[dict] = []
    try:
        for cycle_nodes in nx.simple_cycles(G):
            if len(cycle_nodes) > 5:
                continue
            edge_values = []
            valid = True
            for i in range(len(cycle_nodes)):
                src = cycle_nodes[i]
                dst = cycle_nodes[(i + 1) % len(cycle_nodes)]
                if not G.has_edge(src, dst):
                    valid = False
                    break
                edge_values.append(G.edges[src, dst]["invoice_value"])
            if not valid or not edge_values:
                continue
            cycle_value = sum(edge_values)
            mean_val = cycle_value / len(edge_values) if edge_values else 0
            spread = (
                (max(edge_values) - min(edge_values)) / mean_val * 100
                if mean_val > 0 else 0
            )
            similar = spread <= 30.0
            flag = "CIRCULAR_TRADING" if (cycle_value >= 50_000 and similar) else "POTENTIAL_CYCLE"
            circular_patterns.append({
                "cycle": cycle_nodes,
                "cycle_length": len(cycle_nodes),
                "cycle_value": round(cycle_value, 2),
                "mean_edge_value": round(mean_val, 2),
                "value_spread_pct": round(spread, 2),
                "all_values_similar": similar,
                "flag": flag,
            })
    except Exception as exc:
        log.warning("Circular pattern detection failed: %s", exc)

    circular_patterns.sort(
        key=lambda r: (r["flag"] != "CIRCULAR_TRADING", -r["cycle_value"])
    )

    # ── Use risk_flags from raw data if available ──────────────────
    for gst_key in ("gstr3b", "gstr2a"):
        risk_flags = raw_data.get(gst_key, {}).get("risk_flags", {})
        suspects = risk_flags.get("circular_trading_suspects", [])
        for gstin in suspects:
            if G.has_node(gstin):
                G.nodes[gstin]["is_suspicious"] = True
                # Build a data-flagged circular pattern entry
                if G.has_edge(gstin, company_gstin):
                    edge_val = G.edges[gstin, company_gstin].get("invoice_value", 0)
                    circular_patterns.append({
                        "cycle": [gstin, company_gstin],
                        "cycle_length": 2,
                        "cycle_value": round(edge_val, 2),
                        "mean_edge_value": round(edge_val, 2),
                        "value_spread_pct": 0.0,
                        "all_values_similar": True,
                        "flag": "CIRCULAR_TRADING",
                    })
        # Also flag fictitious vendors from the data
        if risk_flags.get("fictitious_vendors_detected"):
            vendor_summary = raw_data.get("gstr2a", {}).get("vendor_summary", {})
            for vgstin, vinfo in vendor_summary.items():
                if isinstance(vinfo, dict) and not vinfo.get("is_real", True):
                    if G.has_node(vgstin):
                        G.nodes[vgstin]["is_suspicious"] = True

    # ── Also flag ITC mismatch as a kind of suspicious pattern ────────
    itc_summary = (reconciliation_report.get("itc_reconciliation") or {}).get("summary", {})
    gap_pct = itc_summary.get("total_gap_percentage", 0) or 0
    if gap_pct > 20 and not circular_patterns:
        fv_report = (reconciliation_report.get("fictitious_vendor_report") or {})
        fict_gstins = fv_report.get("fictitious_gstins", [])
        for fg in fict_gstins:
            if G.has_node(fg):
                G.nodes[fg]["is_suspicious"] = True

    # ── Serialise nodes & edges ──────────────────────────────────────
    # Compute node risk scores based on graph structure
    circ_gstins = set()
    for p in circular_patterns:
        if p["flag"] == "CIRCULAR_TRADING":
            circ_gstins.update(p["cycle"])

    nodes = []
    for gstin in G.nodes():
        nd = G.nodes[gstin]
        # Calculate a simple risk score
        in_val = sum(d["invoice_value"] for _, _, d in G.in_edges(gstin, data=True))
        out_val = sum(d["invoice_value"] for _, _, d in G.out_edges(gstin, data=True))
        is_circ = gstin in circ_gstins
        risk = 0.8 if is_circ else (0.5 if nd.get("is_suspicious") else 0.2)
        nodes.append({
            "id": gstin,
            "name": nd.get("name", gstin[:15]),
            "total_sales": round(out_val, 2),
            "total_purchases": round(in_val, 2),
            "net_gst_paid": round(out_val * 0.18 - in_val * 0.18, 2),
            "risk_score": risk,
            "is_circular": is_circ,
            "is_suspicious": nd.get("is_suspicious", False),
            "sector": nd.get("sector"),
            "state": gstin[:2] if len(gstin) >= 2 else None,
        })

    circ_edge_set = set()
    for p in circular_patterns:
        cycle = p["cycle"]
        for i in range(len(cycle)):
            circ_edge_set.add((cycle[i], cycle[(i + 1) % len(cycle)]))

    edges = []
    for src, dst, ed in G.edges(data=True):
        edges.append({
            "source": src,
            "target": dst,
            "invoice_value": round(ed.get("invoice_value", 0), 2),
            "tax_amount": round(ed.get("tax_amount", 0), 2),
            "transaction_count": ed.get("transaction_count", 1),
            "is_circular": (src, dst) in circ_edge_set,
        })

    log.info("GST graph: %d nodes, %d edges, %d circular patterns",
             len(nodes), len(edges), len(circular_patterns))
    return nodes, edges, circular_patterns


def ingest_gst(
    gst_files: list[tuple[str, bytes]],   # [(filename, content), ...]
    company_id: str,
) -> dict[str, Any]:
    """
    Run GSTReconciler on uploaded JSON files.
    Returns a dict matching GSTIngestResponse fields.
    """
    from src.gst.reconciler import GSTReconciler

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        found_types: set[str] = set()
        raw_data: dict[str, dict] = {}  # gst_type → parsed data

        for fname, content in gst_files:
            try:
                data = json.loads(content.decode("utf-8"))
            except Exception:
                log.warning("Could not parse GST file %s as JSON", fname)
                continue

            gst_type = _detect_gst_type(data)
            if gst_type == "unknown":
                log.warning("Could not detect GST type for %s", fname)
                continue

            # Normalize to reconciler's expected format
            normalized = _normalize_gst_data(data, gst_type)
            raw_data[gst_type] = normalized

            out_name = f"{company_id}_{gst_type}.json"
            (tmp_path / out_name).write_text(json.dumps(normalized), encoding="utf-8")
            found_types.add(gst_type)

        # If GSTR-1 is missing but we have GSTR-3B, synthesize GSTR-1
        if "gstr1" not in found_types and "gstr3b" in found_types:
            gstr1_syn = _synthesize_gstr1_from_3b(raw_data["gstr3b"])
            raw_data["gstr1"] = gstr1_syn
            out_name = f"{company_id}_gstr1.json"
            (tmp_path / out_name).write_text(json.dumps(gstr1_syn), encoding="utf-8")
            found_types.add("gstr1")
            log.info("Synthesized GSTR-1 from GSTR-3B data for %s", company_id)

        if not found_types:
            return {
                "company_id": company_id,
                "health_score": None,
                "grade": None,
                "verdict": "No valid GST files detected",
                "full_report": None,
            }

        reconciler = GSTReconciler(gst_dir=tmp_path)
        report = reconciler.run_full_reconciliation(company_id)

        hs = report.get("health_score", {})
        itc = (report.get("itc_reconciliation") or {}).get("summary", {})
        tv = (report.get("turnover_reconciliation") or {}).get("summary", {})
        fv = (report.get("fictitious_vendor_report") or {}).get("summary", {})

        # Derive risk flags from reconciliation results
        itc_risk = itc.get("overall_risk", "CLEAN")
        fv_risk = fv.get("risk", "CLEAN")
        gst_itc_fraud_risk = "HIGH" if itc_risk == "HIGH_RISK" else (
            "MEDIUM" if itc_risk == "SUSPICIOUS" else "LOW"
        )

        # ── Build transaction graph & detect circular trading ─────────
        graph_nodes, graph_edges, circular_patterns = _build_gst_graph(
            raw_data, company_id, report
        )
        circular_trading_flag = (
            "HIGH" if any(p["flag"] == "CIRCULAR_TRADING" for p in circular_patterns) else
            "MEDIUM" if circular_patterns else "CLEAR"
        )

        return {
            "company_id": company_id,
            "health_score": hs.get("score"),
            "grade": hs.get("grade"),
            "itc_gap_pct": itc.get("total_gap_percentage"),
            "itc_claimed_3b": itc.get("total_itc_claimed_3b"),
            "itc_available_2a": itc.get("total_itc_as_per_2a"),
            "turnover_consistency": tv.get("overall_bank_to_declared_ratio"),
            "filing_regularity": (hs.get("components", {}).get("filing_regularity") or {}).get("score", 1.0),
            "fictitious_vendor_count": fv.get("fictitious_vendor_count", 0),
            "revenue_inflation_flag": bool(tv.get("revenue_inflation_periods")),
            "circular_trading_flag": circular_trading_flag,
            "gst_itc_fraud_risk": gst_itc_fraud_risk,
            "verdict": hs.get("grade"),
            "full_report": report,
            "graph_nodes": graph_nodes,
            "graph_edges": graph_edges,
            "circular_patterns": circular_patterns,
        }
