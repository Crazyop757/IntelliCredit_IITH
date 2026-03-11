"""
CompanyRepository — CRUD operations on the `companies` table.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CompanyRepository:
    def __init__(self):
        from src.database.supabase_client import get_supabase_admin_client
        self._db = get_supabase_admin_client()

    def upsert_company(
        self,
        *,
        company_id: str,
        name: str,
        cin: str | None = None,
    ) -> dict[str, Any] | None:
        if self._db is None:
            return None
        try:
            row: dict[str, Any] = {"id": company_id, "name": name}
            if cin:
                row["cin"] = cin
            res = (
                self._db.table("companies")
                .upsert(row, on_conflict="id")
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as exc:
            log.error("CompanyRepository.upsert_company failed: %s", exc)
            return None

    def list_companies(self) -> list[dict[str, Any]]:
        if self._db is None:
            return []
        try:
            res = (
                self._db.table("companies")
                .select("id, name, cin, created_at")
                .order("name")
                .execute()
            )
            return res.data or []
        except Exception as exc:
            log.error("CompanyRepository.list_companies failed: %s", exc)
            return []
