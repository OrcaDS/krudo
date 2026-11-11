"""Tests for configuration loading and the CLI.

The autouse fixture in conftest.py clears all settings env vars before each test.
"""

import urllib.error

import pytest

from config.settings import DEFAULT_LISTING_URL, load_settings
from pipeline import cli
from pipeline.cli import main


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


def test_run_all_stops_at_the_first_failing_step(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = []
    for step in ("lake_pull", "ingest", "extract", "lake_push", "transform", "publish_data"):
        code = 1 if step == "transform" else 0
        monkeypatch.setattr(cli, f"_{step}", lambda a, s, n=step, c=code: ran.append(n) or c)
    assert main(["run-all"]) == 1
    assert ran == ["lake_pull", "ingest", "extract", "lake_push", "transform"]  # pushed first


def test_ingest_is_skipped_only_when_doe_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    error: Exception = TimeoutError("timed out")

    def failing_ingest(args, settings):
        raise error

    monkeypatch.setattr(cli, "_ingest", failing_ingest)
    assert cli._ingest_unless_down(None, None) == 0
    error = urllib.error.HTTPError("https://doe.gov.ph", 404, "Not Found", None, None)
    with pytest.raises(urllib.error.HTTPError):  # a moved page needs a person, not a skip
        cli._ingest_unless_down(None, None)


def test_cli_config_error_exits_2_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    assert main(["show-config"]) == 2
