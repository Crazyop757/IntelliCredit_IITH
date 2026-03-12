"""
AppraisalRepository — CRUD operations on the `appraisals` table.
Uses the service-role client so it can write regardless of the authenticated user.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class AppraisalRepository:
    def __init__(self):
        from src.database.supabase_client import get_supabase_admin_client
        self._db = get_supabase_admin_client()

    # ── Create ────────────────────────────────────────────────────────────────

    def create_appraisal(
        self,
        *,
        user_id: str,
        company_id: str,
        company_name: str,
        job_id: str,
        loan_amount_requested: float | None = None,
        fiscal_year: int | None = None,
    ) -> dict[str, Any] | None:
        if self._db is None:
            log.warning("create_appraisal: Supabase admin client is None — cannot persist")
            return None
        try:
            row = {
                "user_id": user_id,
                "company_id": company_id,
                "company_name": company_name,
                "job_id": job_id,
                "status": "PENDING",
            }
            if loan_amount_requested is not None:
                row["loan_amount_requested"] = loan_amount_requested
            if fiscal_year is not None:
                row["fiscal_year"] = fiscal_year
            res = self._db.table("appraisals").insert(row).execute()
            return res.data[0] if res.data else None
        except Exception as exc:
            log.error("AppraisalRepository.create_appraisal failed: %s", exc)
            return None

    # ── Update on pipeline completion ─────────────────────────────────────────

    def update_appraisal_result(
        self,
        *,
        job_id: str,
        status: str,
        result_json: dict[str, Any] | None = None,
        decision: str | None = None,
        risk_band: str | None = None,
        default_probability: float | None = None,
        credit_limit: float | None = None,
        interest_rate: float | None = None,
        cam_storage_path: str | None = None,
        error: str | None = None,
    ) -> None:
        if self._db is None:
            log.warning("update_appraisal_result: Supabase admin client is None — cannot update job %s", job_id)
            return
        try:
            patch: dict[str, Any] = {"status": status}
            if result_json is not None:
                patch["result_json"] = result_json
            if decision is not None:
                patch["decision"] = decision
            if risk_band is not None:
                patch["risk_band"] = risk_band
            if default_probability is not None:
                patch["default_probability"] = default_probability
            if credit_limit is not None:
                patch["credit_limit"] = credit_limit
            if interest_rate is not None:
                patch["interest_rate"] = interest_rate
            if cam_storage_path is not None:
                patch["cam_storage_path"] = cam_storage_path
            if error is not None:
                patch["error"] = error
            self._db.table("appraisals").update(patch).eq("job_id", job_id).execute()
        except Exception as exc:
            log.error("AppraisalRepository.update_appraisal_result failed: %s", exc)

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_appraisals(
        self,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
        company_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if self._db is None:
            log.warning("list_appraisals: Supabase admin client is None — returning empty list")
            return []
        try:
            q = (
                self._db.table("appraisals")
                .select(
                    "id, job_id, company_id, company_name, status, decision, "
                    "risk_band, default_probability, credit_limit, interest_rate, "
                    "loan_amount_requested, fiscal_year, cam_storage_path, "
                    "created_at, updated_at, result_json"
                )
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .range(offset, offset + limit - 1)
            )
            if status:
                q = q.eq("status", status)
            if company_id:
                q = q.eq("company_id", company_id)
            res = q.execute()
            rows = res.data or []
            # Extract risk_score (0-10) from the stored result_json blob
            for row in rows:
                rj = row.pop("result_json", None) or {}
                score_blob = (rj.get("score") or {}) if isinstance(rj, dict) else {}
                row["risk_score"] = score_blob.get("risk_score")
                row["appraisal_date"] = row.get("created_at")
            return rows
        except Exception as exc:
            log.error("AppraisalRepository.list_appraisals failed: %s", exc)
            return []

    def get_appraisal(self, *, appraisal_id: str, user_id: str) -> dict[str, Any] | None:
        if self._db is None:
            log.warning("get_appraisal: Supabase admin client is None — returning None")
            return None
        try:
            res = (
                self._db.table("appraisals")
                .select("*")
                .eq("id", appraisal_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            return res.data
        except Exception as exc:
            log.error("AppraisalRepository.get_appraisal failed: %s", exc)
            return None

    def get_stats(self, *, user_id: str) -> dict[str, Any]:
        if self._db is None:
            log.warning("get_stats: Supabase admin client is None — returning empty stats")
            return {}
        try:
            res = (
                self._db.table("appraisals")
                .select("status, decision, default_probability")
                .eq("user_id", user_id)
                .execute()
            )
            rows = res.data or []
            total = len(rows)
            done = [r for r in rows if r.get("status") == "DONE"]
            approved = sum(1 for r in done if (r.get("decision") or "").upper() in ("PRIME", "APPROVE", "CONDITIONAL"))
            rejected = sum(1 for r in done if (r.get("decision") or "").upper() in ("REJECT", "HARD_REJECT"))
            avg_pd = (
                sum(float(r["default_probability"]) for r in done if r.get("default_probability"))
                / len(done)
                if done else None
            )
            return {
                "total": total,
                "completed": len(done),
                "approved": approved,
                "rejected": rejected,
                "avg_default_probability": round(avg_pd, 4) if avg_pd is not None else None,
            }
        except Exception as exc:
            log.error("AppraisalRepository.get_stats failed: %s", exc)
            return {}
