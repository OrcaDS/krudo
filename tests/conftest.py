"""Shared test setup: isolate every test from the developer's shell environment."""

import pytest

from config.settings import ENV_VARS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all settings env vars so tests see only what they set themselves."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
