from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict

import requests
from requests.adapters import HTTPAdapter, Retry


log = logging.getLogger(__name__)


@dataclass
class TaskFlowClient:
    base_url: str
    token: str

    def __post_init__(self) -> None:
        s = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PATCH", "PUT"],
        )
        s.mount("http://", HTTPAdapter(max_retries=retries))
        s.mount("https://", HTTPAdapter(max_retries=retries))
        self._s = s

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def post_checkin(
        self,
        user: str,
        checkin_date: date,
        yesterday: str,
        today: str,
        blockers: str,
        meta: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/checkins"
        payload: Dict[str, Any] = {
            "user": user,
            "date": checkin_date.isoformat(),
            "yesterday": yesterday,
            "today": today,
            "blockers": blockers,
        }
        if meta:
            payload["meta"] = meta
        log.info("POST %s payload=%s", url, {**payload, "yesterday": "<omitted>", "today": "<omitted>", "blockers": "<omitted>"})
        r = self._s.post(url, headers=self._headers, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_plan(self, user: str, plan_date: date) -> Dict[str, Any]:
        # Try GET first
        url_get = f"{self.base_url.rstrip('/')}/plan"
        params = {"user": user, "date": plan_date.isoformat()}
        try:
            log.info("GET %s params=%s", url_get, params)
            r = self._s.get(url_get, headers=self._headers, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            log.warning("GET plan failed, will try POST: %s", e)
        # Fallback to POST
        log.info("POST %s payload=%s", url_get, params)
        r = self._s.post(url_get, headers=self._headers, json=params, timeout=15)
        r.raise_for_status()
        return r.json()

    # ---- P0 helpers for tasks CRUD used by /ai/apply ----
    def list_tasks(self, status: str = "all") -> list[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/tasks"
        r = self._s.get(url, headers=self._headers, params={"status": status}, timeout=15)
        r.raise_for_status()
        return r.json()  # list

    def add_task(self, **fields) -> dict:
        url = f"{self.base_url.rstrip('/')}/tasks"
        r = self._s.post(url, headers=self._headers, json=fields, timeout=15)
        r.raise_for_status()
        return r.json()

    def update_task(self, task_id: int, **fields) -> dict:
        url = f"{self.base_url.rstrip('/')}/tasks/{task_id}"
        r = self._s.patch(url, headers=self._headers, json=fields, timeout=15)
        r.raise_for_status()
        return r.json()

    def mark_done(self, task_id: int) -> dict:
        return self.update_task(task_id, status="done")

