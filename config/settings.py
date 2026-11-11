"""Single source of pipeline configuration, read from environment variables.

Every variable used here is listed in `.env.example`. Nothing else in the codebase
should read `os.environ` directly.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_USER_AGENT = "krudo/0.1 (+https://github.com/OrcaDS/krudo)"
DEFAULT_LISTING_URL = (
    "https://doe.gov.ph/data-and-prices/liquid-fuels/retail-pump-prices/ncr-pump-prices"
)
MIN_REQUEST_DELAY = 5  # seconds between requests to DOE (project.md §6.1)
# Every env var load_settings() reads (tests clear these to stay independent of the shell)
ENV_VARS = (
    "LOG_LEVEL",
    "LAKE_ROOT",
    "DOE_LISTING_URL",
    "HTTP_USER_AGENT",
    "REQUEST_DELAY_SECONDS",
)


def _env(name: str, default: str) -> str:
    """Return an env var, treating an empty value as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def _float_env(name: str, default: str) -> float:
    """Return an env var as a finite float, with an error that names the variable."""
    raw = _env(name, default)
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds, got {raw!r}") from None
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, got {raw!r}")
    return value


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of all configuration for one pipeline run."""

    log_level: str
    lake_root: Path
    doe_listing_url: str
    http_user_agent: str
    request_delay_seconds: float

    @property
    def duckdb_path(self) -> Path:
        """DuckDB file that dbt builds silver and gold in (rebuilt from bronze every run)."""
        return self.lake_root / "krudo.duckdb"

    def __post_init__(self) -> None:
        if self.log_level not in logging.getLevelNamesMapping():
            raise ValueError(
                f"LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR, got {self.log_level!r}"
            )
        if self.request_delay_seconds < MIN_REQUEST_DELAY:
            raise ValueError(
                f"REQUEST_DELAY_SECONDS must be at least {MIN_REQUEST_DELAY} (be polite to DOE)"
            )


def load_settings() -> Settings:
    """Build Settings from the current environment."""
    return Settings(
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        lake_root=Path(_env("LAKE_ROOT", "./lake")),
        doe_listing_url=_env("DOE_LISTING_URL", DEFAULT_LISTING_URL),
        http_user_agent=_env("HTTP_USER_AGENT", DEFAULT_USER_AGENT),
        request_delay_seconds=_float_env("REQUEST_DELAY_SECONDS", "5"),
    )
