from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class AmapSettings:
    api_key: str
    base_url: str = "https://restapi.amap.com"
    timeout_seconds: float = 8.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.2

    @classmethod
    def from_env(cls) -> "AmapSettings":
        key = os.getenv("AMAP_API_KEY", "").strip()
        if not key:
            raise ValueError("AMAP_API_KEY is required; no API key is read from source or fixture files")
        return cls(key, os.getenv("AMAP_BASE_URL", cls.base_url).rstrip("/"),
                   float(os.getenv("AMAP_TIMEOUT_SECONDS", cls.timeout_seconds)),
                   int(os.getenv("AMAP_MAX_RETRIES", cls.max_retries)),
                   float(os.getenv("AMAP_RETRY_BACKOFF_SECONDS", cls.retry_backoff_seconds)))

