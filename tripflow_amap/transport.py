from __future__ import annotations
import json, urllib.parse, urllib.request
from dataclasses import dataclass
from typing import Any, Callable
@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    json_data: dict[str, Any]
Transport = Callable[[str, dict[str, str], float], HttpResponse]
def urllib_transport(url: str, params: dict[str, str], timeout: float) -> HttpResponse:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return HttpResponse(response.status, json.loads(response.read().decode("utf-8")))

