"""Tests for the local storage backend."""

import os
import time
from pathlib import Path

import pyarrow as pa
import pytest

from config.settings import load_settings
from ingestion.common.storage import TMP_PREFIX, LocalStorage, get_storage

SCHEMA = pa.schema([("product_raw", pa.string()), ("price_raw", pa.string())])


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    root = tmp_path / "lake"
    root.mkdir()
    return root


@pytest.fixture
def storage(lake: Path) -> LocalStorage:
    return LocalStorage(lake)


def test_bytes_round_trip(storage: LocalStorage) -> None:
    storage.write_bytes("bronze/files/doe/ncr/a.pdf", b"%PDF-1.7")
    assert storage.exists("bronze/files/doe/ncr/a.pdf")
    assert storage.read_bytes("bronze/files/doe/ncr/a.pdf") == b"%PDF-1.7"


def test_list_is_sorted_and_relative(storage: LocalStorage) -> None:
    for name in ["b.pdf", "a.pdf", "sub/c.pdf"]:
        storage.write_bytes(f"bronze/files/{name}", b"x")
    assert storage.list("bronze/files") == [
        "bronze/files/a.pdf",
        "bronze/files/b.pdf",
        "bronze/files/sub/c.pdf",
    ]
    assert storage.list("does/not/exist") == []


def test_list_matches_bucket_prefix_semantics(storage: LocalStorage) -> None:
    storage.write_bytes("bronze/files/a.pdf", b"x")
    storage.write_bytes("bronze/files/report.tmp", b"x")  # a real file, not a temp file
    assert storage.list("bronze/files/a.pdf") == ["bronze/files/a.pdf"]  # prefix is a file
    assert storage.list() == ["bronze/files/a.pdf", "bronze/files/report.tmp"]  # whole lake


def test_parquet_overwrite_is_idempotent(storage: LocalStorage) -> None:
    table = pa.table({"product_raw": ["RON 95"], "price_raw": ["n/a"]}, schema=SCHEMA)
    path = "bronze/tables/doe_prices/year=2026/part-x.parquet"
    storage.write_parquet(path, table, SCHEMA)
    storage.write_parquet(path, table, SCHEMA)
    result = storage.read_parquet(path)
    assert result.num_rows == 1
    assert result.schema.equals(SCHEMA)
    assert result.column("price_raw").to_pylist() == ["n/a"]  # bronze keeps raw text


def test_parquet_rejects_data_that_does_not_fit_schema(storage: LocalStorage) -> None:
    table = pa.table({"product_raw": ["RON 95"], "price_raw": ["n/a"]})
    wrong = pa.schema([("product_raw", pa.string()), ("price_raw", pa.float64())])
    with pytest.raises(pa.ArrowInvalid):
        storage.write_parquet("bronze/tables/x.parquet", table, wrong)


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "../outside.txt",
        "bronze/../../x",
        "",
        "..\\x",  # Windows-style traversal
        "a\\..\\..\\x",
        "D:/evil",  # drive letter
        "C:evil",
        f"bronze/{TMP_PREFIX}abc-a.pdf",  # reserved temp name
    ],
)
def test_rejects_paths_outside_lake(storage: LocalStorage, lake: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        storage.write_bytes(bad, b"x")
    assert not any(lake.parent.glob("x")) and not any(lake.parent.glob("outside.txt"))


def test_no_temp_files_left_behind(storage: LocalStorage, lake: Path) -> None:
    storage.write_bytes("bronze/files/a.pdf", b"x")
    assert not list(lake.rglob(f"{TMP_PREFIX}*"))


def test_failed_write_cleans_up_and_keeps_old_file(storage: LocalStorage, lake: Path) -> None:
    storage.write_bytes("bronze/files/a.pdf", b"old")

    def boom(tmp: Path) -> None:
        tmp.write_bytes(b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError):
        storage._atomic_write("bronze/files/a.pdf", boom)
    assert storage.read_bytes("bronze/files/a.pdf") == b"old"
    assert not list(lake.rglob(f"{TMP_PREFIX}*"))


def test_replace_retries_while_windows_holds_the_file(
    storage: LocalStorage, lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replace, calls = os.replace, []

    def locked_once(src: Path, dst: Path) -> None:
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError(5, "Access is denied")
        replace(src, dst)

    monkeypatch.setattr(os, "replace", locked_once)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    storage.write_bytes("bronze/files/a.pdf", b"new")
    assert storage.read_bytes("bronze/files/a.pdf") == b"new"
    assert len(calls) == 2

    def always_locked(src: Path, dst: Path) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(os, "replace", always_locked)
    with pytest.raises(PermissionError):  # still locked after the last retry
        storage.write_bytes("bronze/files/b.pdf", b"x")
    assert not list(lake.rglob(f"{TMP_PREFIX}*"))


def test_get_storage_defaults_to_local(monkeypatch: pytest.MonkeyPatch, lake: Path) -> None:
    monkeypatch.setenv("LAKE_ROOT", str(lake))
    assert isinstance(get_storage(load_settings()), LocalStorage)
