"""VictoriaLogs HTTP client."""

from __future__ import annotations

import json
import sys
import urllib.parse
from typing import Any

from hops._format import info
from hops._runner import tools_curl

VL_URL = "http://victoria-logs-single.observability:9428"


class VictoriaLogsClient:
    """Client for querying VictoriaLogs."""

    def __init__(self, base_url: str = VL_URL):
        self.base_url = base_url.rstrip("/")

    def _post(self, endpoint: str, params: dict[str, str]) -> str:
        """POST to VictoriaLogs via rook-ceph-tools pod."""
        url = f"{self.base_url}{endpoint}"
        data = urllib.parse.urlencode(params)
        return tools_curl(
            url,
            method="POST",
            data=data,
            timeout=60,
            service_name="VictoriaLogs",
        )

    def _post_json(self, endpoint: str, params: dict[str, str]) -> Any:
        raw = self._post(endpoint, params)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            info("error: invalid JSON from VictoriaLogs")
            sys.exit(1)

    def query_logs(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"query": query}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if limit:
            params["limit"] = str(limit)
        raw = self._post("/select/logsql/query", params)
        logs = []
        for line in raw.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return logs

    def query_stats(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        time: str | None = None,
    ) -> Any:
        params: dict[str, str] = {"query": query}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if time:
            params["time"] = time
        return self._post_json("/select/logsql/stats_query", params)

    def query_stats_range(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        step: str = "1h",
    ) -> Any:
        params: dict[str, str] = {"query": query, "step": step}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._post_json("/select/logsql/stats_query_range", params)

    def query_hits(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        step: str = "1h",
        field: list[str] | None = None,
    ) -> Any:
        params: dict[str, str] = {"query": query, "step": step}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        # Handle multiple field parameters by constructing raw data
        if field:
            data_parts = [
                f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()
            ]
            for f in field:
                data_parts.append(f"field={urllib.parse.quote(f)}")
            raw_data = "&".join(data_parts)
            raw = tools_curl(
                f"{self.base_url}/select/logsql/hits",
                method="POST",
                data=raw_data,
                timeout=60,
                service_name="VictoriaLogs",
            )
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                info("error: invalid JSON from VictoriaLogs")
                sys.exit(1)
        return self._post_json("/select/logsql/hits", params)

    def query_field_names(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"query": query}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        result = self._post_json("/select/logsql/field_names", params)
        return result.get("values", [])
