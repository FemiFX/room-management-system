from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class NextcloudConfig:
    base_url: str
    admin_user: str
    app_password: str
    ocs_version: str = "v2"
    timeout_s: int = 30
    page_size: int = 100


class NextcloudOCSClient:
    def __init__(self, cfg: NextcloudConfig) -> None:
        try:
            import requests
            from requests.auth import HTTPBasicAuth
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise RuntimeError("requests is required for Nextcloud sync integration.") from exc

        self.cfg = cfg
        self.sess = requests.Session()
        self.sess.headers.update(
            {
                "OCS-APIRequest": "true",
                "Accept": "application/json",
            }
        )
        self.auth = HTTPBasicAuth(cfg.admin_user, cfg.app_password)

    def _ocs(
        self,
        path: str,
        *,
        params: dict | None = None,
        data: dict | None = None,
        method: str = "get",
        retries: int = 3,
    ) -> dict:
        base = self.cfg.base_url.rstrip("/")
        url = f"{base}/ocs/{self.cfg.ocs_version}.php/cloud/{path.lstrip('/')}"
        params = params or {}
        params.setdefault("format", "json")
        data = data or {}

        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                response = self.sess.request(
                    method=method.lower(),
                    url=url,
                    params=params,
                    data=data,
                    auth=self.auth,
                    timeout=self.cfg.timeout_s,
                )
                response.raise_for_status()
                payload = response.json()

                meta = payload.get("ocs", {}).get("meta", {})
                status = str(meta.get("status", "")).lower()
                try:
                    statuscode = int(meta.get("statuscode", 0))
                except (TypeError, ValueError):
                    statuscode = 0

                if status == "ok" or statuscode in (100, 200):
                    return payload.get("ocs", {}).get("data", {})
                raise RuntimeError(
                    f"OCS statuscode={statuscode}, status={meta.get('status')}, "
                    f"message={meta.get('message')}"
                )
            except Exception as exc:  # pragma: no cover - retry logic
                last_exc = exc
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"OCS call failed after retries: {url}") from last_exc

    def list_users(self, search: str = "") -> list[str]:
        users: list[str] = []
        offset = 0
        while True:
            data = self._ocs(
                "users",
                params={"search": search, "limit": self.cfg.page_size, "offset": offset},
            )
            batch = data.get("users", [])
            if not batch:
                break
            users.extend(batch)
            offset += len(batch)
        return users

    def user_info(self, user_id: str) -> dict:
        data = self._ocs(f"users/{user_id}")
        return data if isinstance(data, dict) else {}
