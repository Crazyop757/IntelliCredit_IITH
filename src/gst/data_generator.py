"""
data_generator.py — Synthetic GST data generator for intelli_credit.

Generates realistic GSTR-1, GSTR-2A, and GSTR-3B filings for test /
model-training purposes, with optional fraud injection covering three
canonical patterns used in Indian GST evasion cases:

  1. ITC over-claim   – GSTR-3B itc_claimed is 25-40 % above what GSTR-2A
                        auto-populated returns show.
  2. Fictitious vendors – 3-4 supplier GSTINs appear in GSTR-3B ITC
                        schedules but are absent from GSTR-2A.
  3. Circular trading  – Company A bills B, B bills C, C bills A at the
                        same amounts (carousel / round-tripping fraud).

Output files (written to data/raw/gst/):
  {company_id}_gstr1.json          – outward supplies
  {company_id}_gstr2a.json         – auto-populated inward supplies
  {company_id}_gstr3b.json         – self-declared monthly summary
  gst_transaction_graph.json       – all inter-company invoice edges
                                     (updated incrementally across calls)
"""

from __future__ import annotations

import json
import random
import string
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]   # …/intelli_credit/
GST_RAW_DIR   = _PROJECT_ROOT / "data" / "raw" / "gst"
GST_RAW_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Valid Indian state/UT codes (01-37)
_STATE_CODES = [f"{i:02d}" for i in range(1, 38)]

# Standard GST rate slabs (5 %, 12 %, 18 %, 28 %)
_GST_RATES = [0.05, 0.12, 0.18, 0.28]

# Default fiscal year start (April of this year)
_DEFAULT_FY_START_YEAR  = 2024
_DEFAULT_FY_START_MONTH = 4   # April


# ---------------------------------------------------------------------------
# GSTDataGenerator
# ---------------------------------------------------------------------------

class GSTDataGenerator:
    """
    Generates synthetic GST filings (GSTR-1, GSTR-2A, GSTR-3B).

    Parameters
    ----------
    seed:
        Seed for reproducibility.  The same seed + company_id always produces
        the same GSTIN and the same data shape.

    Example
    -------
    >>> gen = GSTDataGenerator(seed=42)
    >>> result = gen.generate_company_data("ALPHA_CORP", months=12, inject_fraud=False)
    >>> fraud = gen.generate_company_data("SHELL_CO", months=6, inject_fraud=True)
    """

    def __init__(self, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        # Persistent company-id → GSTIN map so the same id always maps to the
        # same GSTIN across multiple calls within one generator instance.
        self._company_gstin: dict[str, str] = {}

    # ------------------------------------------------------------------
    # GSTIN helpers
    # ------------------------------------------------------------------

    def _make_gstin(self, company_id: str | None = None) -> str:
        """
        Return a syntactically valid GSTIN.

        If *company_id* is given, the result is deterministic and cached.
        Otherwise a fresh random GSTIN is returned on every call.
        """
        if company_id and company_id in self._company_gstin:
            return self._company_gstin[company_id]

        state = self.rng.choice(_STATE_CODES)
        # PAN: AAAAA9999A format
        pan = (
            "".join(self.rng.choices(string.ascii_uppercase, k=5))
            + "".join(self.rng.choices(string.digits, k=4))
            + self.rng.choice(string.ascii_uppercase)
        )
        entity_num = str(self.rng.randint(1, 9))
        body14 = state + pan + entity_num + "Z"
        gstin  = body14 + self._gstin_checksum(body14)

        if company_id:
            self._company_gstin[company_id] = gstin
        return gstin

    @staticmethod
    def _gstin_checksum(body14: str) -> str:
        """
        Compute the 15th (checksum) character of a 14-character GSTIN prefix
        using the GST Council's Luhn-derived algorithm.
        """
        total = 0
        for i, ch in enumerate(body14):
            val = _GSTIN_CHARS.index(ch)
            if i % 2 == 1:     # even 1-based positions → factor 2
                val *= 2
            total += val // 36 + val % 36
        return _GSTIN_CHARS[total % 36]

    # ------------------------------------------------------------------
    # Invoice number / date helpers
    # ------------------------------------------------------------------

    def _invoice_number(
        self, company_id: str, year: int, month: int, seq: int
    ) -> str:
        prefix     = company_id.upper().replace(" ", "").replace("_", "")[:5]
        fy_suffix  = str(year + 1)[-2:]
        return f"{prefix}/{year}-{fy_suffix}/{month:02d}/{seq:05d}"

    def _random_date_in_month(self, year: int, month: int) -> str:
        """Return a random ISO-8601 date string within the given year-month."""
        if month == 12:
            last_day = 31
        else:
            last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
        return date(year, month, self.rng.randint(1, last_day)).isoformat()

    # ------------------------------------------------------------------
    # Tax computation
    # ------------------------------------------------------------------

    @staticmethod
    def _split_tax(
        taxable: float, rate: float, inter_state: bool
    ) -> tuple[float, float, float]:
        """
        Return (igst, cgst, sgst).

        For inter-state supplies the full tax goes to IGST.
        For intra-state supplies the tax is split equally between CGST and SGST.
        """
        total_tax = round(taxable * rate, 2)
        if inter_state:
            return total_tax, 0.0, 0.0
        half = round(total_tax / 2, 2)
        return 0.0, half, half

    # ------------------------------------------------------------------
    # Period helper
    # ------------------------------------------------------------------

    @staticmethod
    def _period_from_offset(
        fy_start_year: int, fy_start_month: int, m_offset: int
    ) -> tuple[int, int, str]:
        """Return (year, month, period_key) for *m_offset* months after start."""
        raw   = fy_start_month + m_offset
        year  = fy_start_year + (raw - 1) // 12
        month = ((raw - 1) % 12) + 1
        return year, month, f"{year}-{month:02d}"

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate_company_data(
        self,
        company_id: str,
        months: int = 12,
        inject_fraud: bool = False,
    ) -> dict[str, Any]:
        """
        Generate GSTR-1, GSTR-2A, and GSTR-3B filings for *company_id*.

        Parameters
        ----------
        company_id:
            Logical name / identifier (e.g. ``"ALPHA_CORP"``).  A stable
            GSTIN is derived internally and reused across calls.
        months:
            Number of monthly periods to generate (default 12 ≈ one FY).
        inject_fraud:
            When ``True``, injects three fraud patterns:

            1. **ITC inflation** – GSTR-3B ``itc_claimed`` is 25-40 % above
               the total ITC visible in GSTR-2A.
            2. **Fictitious vendors** – 3-4 supplier GSTINs appear in the
               GSTR-3B ITC schedule but never show up in GSTR-2A.
            3. **Circular trading** – invoices form the ring
               *company_id* → B → C → *company_id* with identical amounts
               so ITC is recycled without real economic substance.

        Returns
        -------
        dict
            ``{"gstr1": ..., "gstr2a": ..., "gstr3b": ...}``

        Side-effects
        ------------
        Writes four JSON files to ``data/raw/gst/``:

        * ``{company_id}_gstr1.json``
        * ``{company_id}_gstr2a.json``
        * ``{company_id}_gstr3b.json``
        * ``gst_transaction_graph.json``  *(incrementally updated)*
        """
        own_gstin = self._make_gstin(company_id)

        # Fixed buyer / supplier pools so the same other-parties recur each month.
        buyer_pool    = [self._make_gstin() for _ in range(self.rng.randint(8, 14))]
        supplier_pool = [self._make_gstin() for _ in range(self.rng.randint(8, 14))]

        fy_start_year  = _DEFAULT_FY_START_YEAR
        fy_start_month = _DEFAULT_FY_START_MONTH

        # ------------------------------------------------------------------
        # GSTR-1  –  outward supplies (what company_id sold)
        # ------------------------------------------------------------------
        gstr1_invoices: list[dict] = []
        monthly_outward: dict[str, dict] = {}

        for m_offset in range(months):
            year, month, period_key = self._period_from_offset(
                fy_start_year, fy_start_month, m_offset
            )
            n_invoices = self.rng.randint(10, 50)
            m_taxable = m_igst = m_cgst = m_sgst = 0.0

            for seq in range(1, n_invoices + 1):
                buyer     = self.rng.choice(buyer_pool)
                is_inter  = buyer[:2] != own_gstin[:2]
                rate      = self.rng.choice(_GST_RATES)
                taxable   = round(self.rng.uniform(10_000, 1_000_000), 2)
                igst, cgst, sgst = self._split_tax(taxable, rate, is_inter)

                gstr1_invoices.append({
                    "period":          period_key,
                    "supplier_gstin":  own_gstin,
                    "buyer_gstin":     buyer,
                    "invoice_number":  self._invoice_number(company_id, year, month, seq),
                    "invoice_date":    self._random_date_in_month(year, month),
                    "taxable_value":   taxable,
                    "igst":            igst,
                    "cgst":            cgst,
                    "sgst":            sgst,
                    "gst_rate":        rate,
                    "inter_state":     is_inter,
                })
                m_taxable += taxable
                m_igst    += igst
                m_cgst    += cgst
                m_sgst    += sgst

            monthly_outward[period_key] = {
                "taxable":   round(m_taxable, 2),
                "igst":      round(m_igst, 2),
                "cgst":      round(m_cgst, 2),
                "sgst":      round(m_sgst, 2),
                "total_tax": round(m_igst + m_cgst + m_sgst, 2),
            }

        # ------------------------------------------------------------------
        # GSTR-2A  –  auto-populated inward supplies from suppliers' GSTR-1
        # ------------------------------------------------------------------
        gstr2a_invoices: list[dict] = []
        monthly_inward: dict[str, dict] = {}

        for m_offset in range(months):
            year, month, period_key = self._period_from_offset(
                fy_start_year, fy_start_month, m_offset
            )
            n_invoices = self.rng.randint(8, 40)
            m_igst = m_cgst = m_sgst = 0.0

            for seq in range(1, n_invoices + 1):
                # ~2 % of supplier invoices are absent (supplier hasn't filed yet)
                if self.rng.random() < 0.02:
                    continue

                supplier  = self.rng.choice(supplier_pool)
                is_inter  = supplier[:2] != own_gstin[:2]
                rate      = self.rng.choice(_GST_RATES)
                base      = round(self.rng.uniform(5_000, 500_000), 2)

                # ~7 % have minor discrepancies vs. what the supplier reported
                discrepancy = self.rng.random() < 0.07
                taxable = round(base * self.rng.uniform(0.95, 1.05), 2) if discrepancy else base

                igst, cgst, sgst = self._split_tax(taxable, rate, is_inter)

                gstr2a_invoices.append({
                    "period":          period_key,
                    "supplier_gstin":  supplier,
                    "buyer_gstin":     own_gstin,
                    "invoice_number":  (
                        f"SUP{supplier[:6]}/{year}/{month:02d}/{seq:04d}"
                    ),
                    "invoice_date":    self._random_date_in_month(year, month),
                    "taxable_value":   taxable,
                    "igst":            igst,
                    "cgst":            cgst,
                    "sgst":            sgst,
                    "gst_rate":        rate,
                    "inter_state":     is_inter,
                    "discrepancy":     discrepancy,
                })
                m_igst += igst
                m_cgst += cgst
                m_sgst += sgst

            monthly_inward[period_key] = {
                "igst":      round(m_igst, 2),
                "cgst":      round(m_cgst, 2),
                "sgst":      round(m_sgst, 2),
                "total_itc": round(m_igst + m_cgst + m_sgst, 2),
            }

        # ------------------------------------------------------------------
        # Fraud injection
        # ------------------------------------------------------------------
        fictitious_gstins: list[str] = []
        circular_invoices: list[dict] = []

        if inject_fraud:
            # ---- Pattern 2: Fictitious vendor GSTINs (3-4 new ones) ---------
            fictitious_gstins = [
                self._make_gstin()
                for _ in range(self.rng.randint(3, 4))
            ]

            # ---- Pattern 3: Circular trading  A → B → C → A ----------------
            # Use stable internal keys so the ring GSTINs are reproducible.
            circ_b_gstin = self._make_gstin(f"__CIRC_B__{company_id}")
            circ_c_gstin = self._make_gstin(f"__CIRC_C__{company_id}")

            # Use the first generated period for the ring transaction.
            ring_year, ring_month, ring_period = self._period_from_offset(
                fy_start_year, fy_start_month, 0
            )
            circ_amount = round(self.rng.uniform(500_000, 5_000_000), 2)
            circ_rate   = 0.18
            circ_tax    = round(circ_amount * circ_rate, 2)

            # Leg A→B  (shows in company_id's GSTR-1)
            inv_ab = {
                "period":          ring_period,
                "supplier_gstin":  own_gstin,
                "buyer_gstin":     circ_b_gstin,
                "invoice_number":  f"{company_id.upper()[:5]}/CIRC/{ring_year}/AB/00001",
                "invoice_date":    self._random_date_in_month(ring_year, ring_month),
                "taxable_value":   circ_amount,
                "igst":            circ_tax,
                "cgst":            0.0,
                "sgst":            0.0,
                "gst_rate":        circ_rate,
                "inter_state":     True,
                "circular_fraud":  True,
            }
            # Leg B→C  (graph-only; neither in company_id's GSTR-1 nor 2A)
            inv_bc = {
                "period":          ring_period,
                "supplier_gstin":  circ_b_gstin,
                "buyer_gstin":     circ_c_gstin,
                "invoice_number":  f"CIRC_B_{company_id[:5]}/CIRC/{ring_year}/BC/00001",
                "invoice_date":    self._random_date_in_month(ring_year, ring_month),
                "taxable_value":   circ_amount,
                "igst":            circ_tax,
                "cgst":            0.0,
                "sgst":            0.0,
                "gst_rate":        circ_rate,
                "inter_state":     True,
                "circular_fraud":  True,
            }
            # Leg C→A  (shows in company_id's GSTR-2A as inward supply)
            inv_ca = {
                "period":          ring_period,
                "supplier_gstin":  circ_c_gstin,
                "buyer_gstin":     own_gstin,
                "invoice_number":  f"CIRC_C_{company_id[:5]}/CIRC/{ring_year}/CA/00001",
                "invoice_date":    self._random_date_in_month(ring_year, ring_month),
                "taxable_value":   circ_amount,
                "igst":            circ_tax,
                "cgst":            0.0,
                "sgst":            0.0,
                "gst_rate":        circ_rate,
                "inter_state":     True,
                "discrepancy":     False,
                "circular_fraud":  True,
            }

            # Inject into the respective returns
            gstr1_invoices.append(inv_ab)
            gstr2a_invoices.append(inv_ca)
            circular_invoices = [inv_ab, inv_bc, inv_ca]

            # Update monthly totals so GSTR-3B arithmetic remains self-consistent
            out = monthly_outward[ring_period]
            out["taxable"]   = round(out["taxable"]   + circ_amount, 2)
            out["igst"]      = round(out["igst"]       + circ_tax,   2)
            out["total_tax"] = round(out["total_tax"]  + circ_tax,   2)

            iw = monthly_inward[ring_period]
            iw["igst"]      = round(iw["igst"]      + circ_tax, 2)
            iw["total_itc"] = round(iw["total_itc"] + circ_tax, 2)

        # ------------------------------------------------------------------
        # GSTR-3B  –  self-declared monthly summary
        # ------------------------------------------------------------------
        gstr3b_filings: list[dict] = []

        for period_key, out_data in monthly_outward.items():
            iw_data    = monthly_inward.get(
                period_key,
                {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "total_itc": 0.0},
            )
            actual_itc = iw_data["total_itc"]

            if inject_fraud:
                # Pattern 1: inflate ITC claim by 25-40 %
                inflation_factor = self.rng.uniform(1.25, 1.40)
                itc_claimed      = round(actual_itc * inflation_factor, 2)

                # Pattern 2: fictitious vendor ITC entries (spread across all months)
                fictitious_entries: list[dict] = []
                for f_gstin in fictitious_gstins:
                    f_taxable = round(self.rng.uniform(50_000, 300_000), 2)
                    f_tax_amt = round(f_taxable * 0.18, 2)
                    fictitious_entries.append({
                        "supplier_gstin": f_gstin,
                        "invoice_number": (
                            f"FAKE{f_gstin[:6]}/{period_key}/INV"
                        ),
                        "taxable_value":  f_taxable,
                        "itc_amount":     f_tax_amt,
                        "note":           "fictitious_vendor",
                    })
            else:
                # Realistic: claim 90-100 % of available ITC (some may not be claimed)
                itc_claimed      = round(actual_itc * self.rng.uniform(0.90, 1.00), 2)
                fictitious_entries = []

            net_tax_paid = max(0.0, round(out_data["total_tax"] - itc_claimed, 2))

            filing: dict[str, Any] = {
                "period":                   period_key,
                "gstin":                    own_gstin,
                "total_taxable_turnover":   out_data["taxable"],
                "outward_tax_liability": {
                    "igst":  out_data["igst"],
                    "cgst":  out_data["cgst"],
                    "sgst":  out_data["sgst"],
                    "total": out_data["total_tax"],
                },
                "itc_available": {
                    "igst":  iw_data["igst"],
                    "cgst":  iw_data["cgst"],
                    "sgst":  iw_data["sgst"],
                    "total": actual_itc,
                },
                "itc_claimed": itc_claimed,
                "tax_paid":    net_tax_paid,
            }

            if inject_fraud:
                filing["fictitious_itc_entries"] = fictitious_entries
                filing["fraud_flags"] = {
                    "itc_inflation":      True,
                    "fictitious_vendors": len(fictitious_gstins),
                    "circular_trading":   True,
                }

            gstr3b_filings.append(filing)

        # ------------------------------------------------------------------
        # Assemble return payloads
        # ------------------------------------------------------------------
        gstr1: dict[str, Any] = {
            "company_id": company_id,
            "gstin":      own_gstin,
            "form":       "GSTR-1",
            "description": "Outward supplies (sales) declared by the taxpayer",
            "invoices":   gstr1_invoices,
        }
        gstr2a: dict[str, Any] = {
            "company_id":              company_id,
            "gstin":                   own_gstin,
            "form":                    "GSTR-2A",
            "description":             (
                "Auto-populated inward supplies from counter-party GSTR-1 filings"
            ),
            "auto_populated_invoices": gstr2a_invoices,
        }
        gstr3b: dict[str, Any] = {
            "company_id": company_id,
            "gstin":      own_gstin,
            "form":       "GSTR-3B",
            "description": "Self-declared monthly summary return",
            "filings":    gstr3b_filings,
        }

        # ------------------------------------------------------------------
        # Persist individual return files
        # ------------------------------------------------------------------
        _write_json(GST_RAW_DIR / f"{company_id}_gstr1.json",  gstr1)
        _write_json(GST_RAW_DIR / f"{company_id}_gstr2a.json", gstr2a)
        _write_json(GST_RAW_DIR / f"{company_id}_gstr3b.json", gstr3b)

        # ------------------------------------------------------------------
        # Update the combined transaction graph
        # ------------------------------------------------------------------
        self._update_transaction_graph(
            gstr1_invoices, gstr2a_invoices, circular_invoices
        )

        return {"gstr1": gstr1, "gstr2a": gstr2a, "gstr3b": gstr3b}

    # ------------------------------------------------------------------
    # Transaction graph
    # ------------------------------------------------------------------

    @staticmethod
    def _update_transaction_graph(
        gstr1_invoices:    list[dict],
        gstr2a_invoices:   list[dict],
        circular_invoices: list[dict],
    ) -> None:
        """
        Incrementally update ``gst_transaction_graph.json``.

        The graph stores all unique inter-company invoice edges seen across
        every call to :meth:`generate_company_data`.  The B→C leg of a
        circular ring (which does not appear in any single company's GSTR-1
        or GSTR-2A) is added here from *circular_invoices*.

        Graph schema::

            {
              "nodes": {
                "<gstin>": {
                  "gstin": "...",
                  "total_supplied":  <float>,   # cumulative taxable value sold
                  "total_purchased": <float>    # cumulative taxable value bought
                },
                ...
              },
              "edges": [
                {
                  "invoice_number":  "...",
                  "period":          "YYYY-MM",
                  "supplier_gstin":  "...",
                  "buyer_gstin":     "...",
                  "taxable_value":   <float>,
                  "igst":            <float>,
                  "cgst":            <float>,
                  "sgst":            <float>,
                  "circular_fraud":  <bool>
                },
                ...
              ]
            }
        """
        graph_path = GST_RAW_DIR / "gst_transaction_graph.json"

        if graph_path.exists():
            with graph_path.open("r", encoding="utf-8") as fh:
                graph: dict = json.load(fh)
        else:
            graph = {"nodes": {}, "edges": []}

        # Build the full invoice list for this call.
        # GSTR-2A invoices for company_id give us supplier→company_id edges;
        # they duplicate what those suppliers declared in their own GSTR-1, so
        # we keep them for completeness.
        # For the circular ring, inv_ab and inv_ca are already in GSTR-1 /
        # GSTR-2A; only inv_bc (B→C) is unique to circular_invoices.
        all_invoices: list[dict] = list(gstr1_invoices) + list(gstr2a_invoices)
        existing_inv_nums_local: set[str] = {
            inv["invoice_number"] for inv in all_invoices
        }
        for inv in circular_invoices:
            if inv["invoice_number"] not in existing_inv_nums_local:
                all_invoices.append(inv)
                existing_inv_nums_local.add(inv["invoice_number"])

        # Existing edge keys in the persisted graph (avoid duplicates)
        existing_global: set[str] = {
            e["invoice_number"] for e in graph["edges"]
        }

        for inv in all_invoices:
            sup_gstin = inv["supplier_gstin"]
            buy_gstin = inv["buyer_gstin"]
            taxable   = inv["taxable_value"]

            # Ensure nodes exist
            for gstin in (sup_gstin, buy_gstin):
                if gstin not in graph["nodes"]:
                    graph["nodes"][gstin] = {
                        "gstin":           gstin,
                        "total_supplied":  0.0,
                        "total_purchased": 0.0,
                    }

            # Accumulate node-level totals (even for duplicate invoices the
            # intent is to reflect running totals; duplicates are only skipped
            # at the edge level).
            graph["nodes"][sup_gstin]["total_supplied"]  += taxable
            graph["nodes"][buy_gstin]["total_purchased"] += taxable

            # Append edge only once
            if inv["invoice_number"] not in existing_global:
                graph["edges"].append({
                    "invoice_number":  inv["invoice_number"],
                    "period":          inv["period"],
                    "supplier_gstin":  sup_gstin,
                    "buyer_gstin":     buy_gstin,
                    "taxable_value":   taxable,
                    "igst":            inv["igst"],
                    "cgst":            inv["cgst"],
                    "sgst":            inv["sgst"],
                    "circular_fraud":  inv.get("circular_fraud", False),
                })
                existing_global.add(inv["invoice_number"])

        # Round node totals to avoid floating-point drift
        for node in graph["nodes"].values():
            node["total_supplied"]  = round(node["total_supplied"],  2)
            node["total_purchased"] = round(node["total_purchased"], 2)

        _write_json(graph_path, graph)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: Any) -> None:
    """Write *data* as indented JSON to *path*, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("Generating synthetic GST data …")

    gen = GSTDataGenerator(seed=42)

    companies = [
        ("ALPHA_CORP",  False),
        ("BETA_TRADERS", False),
        ("SHELL_CO_X",   True),   # fraudulent entity
    ]

    for cid, fraud in companies:
        result = gen.generate_company_data(cid, months=12, inject_fraud=fraud)
        g1  = result["gstr1"]
        g2a = result["gstr2a"]
        g3b = result["gstr3b"]
        label = " [FRAUD]" if fraud else ""
        print(
            f"  {cid}{label}: "
            f"{len(g1['invoices'])} GSTR-1 invoices | "
            f"{len(g2a['auto_populated_invoices'])} GSTR-2A invoices | "
            f"{len(g3b['filings'])} GSTR-3B periods"
        )

    graph_path = GST_RAW_DIR / "gst_transaction_graph.json"
    with graph_path.open() as fh:
        graph = json.load(fh)
    print(
        f"\nTransaction graph: "
        f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges"
    )
    print(f"Output directory: {GST_RAW_DIR}")
    sys.exit(0)
