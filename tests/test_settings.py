"""Tests for configuration loading and the CLI skeleton.

The autouse fixture in conftest.py clears all settings env vars before each test.
"""

import pytest

from config.settings import DEFAULT_LISTING_URL, load_settings
from pipeline.cli import PLANNED, main


def test_defaults_need_no_environment() -> None:
    s = load_settings()
    assert s.request_delay_seconds == 5
    assert s.doe_listing_url == DEFAULT_LISTING_URL
    assert s.log_level == "INFO"
    assert "@" not in s.http_user_agent  # no personal email sent to DOE


def test_empty_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOE_LISTING_URL", "")
    assert load_settings().doe_listing_url == DEFAULT_LISTING_URL


@pytest.mark.parametrize(
    ("value", "message"),
    [("4.9", "polite"), ("nan", "finite"), ("inf", "finite"), ("5s", "REQUEST_DELAY_SECONDS")],
)
def test_request_delay_validated(monkeypatch: pytest.MonkeyPatch, value: str, message: str) -> None:
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", value)
    with pytest.raises(ValueError, match=message):
        load_settings()


def test_log_level_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        load_settings()
    monkeypatch.setenv("LOG_LEVEL", "debug")  # case-insensitive
    assert load_settings().log_level == "DEBUG"


def test_cli_show_config_succeeds() -> None:
    assert main(["show-config"]) == 0


@pytest.mark.parametrize("command", PLANNED)
def test_unbuilt_commands_fail_loudly(command: str) -> None:
    assert main([command]) == 2  # a scheduled run must never pass while doing nothing


def test_cli_config_error_exits_2_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    assert main(["show-config"]) == 2
